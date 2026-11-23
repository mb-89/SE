"""Generate the Copilot and Claude Code layouts of the se plugin from its one source in `src/`.

Every agent (`src/agents/<name>.md`) and every skill (`src/skills/<name>/...`) is written once.
`build` writes both layouts, the Claude Code plugin manifests, Copilot's hooks
(`.github/hooks/se.json` for the repository, `.github/plugin/hooks.json` for a plugin install, both a
layout setting: `Layout.hooks`), Copilot's one plugin manifest
(`.github/plugin/plugin.json`, or the root `plugin.json` where `se.toml` `[plugin] copilot_manifest`
is `"root"`) and the MCP door's declarations (`.github/mcp.json`, and a root
`.mcp.json` only where `se.toml` `[plugin] root_mcp` is on, and the Claude Code manifest's
`mcpServers` only where `[plugin] claude_mcp` is on). Whether the PowerShell lines of both
hooks files call a bare `bash` or the Git-bash hand-off `scripts/bash.ps1` is the build setting
`se.toml` `[plugin] powershell_hooks` (`powershell_hooks`); unset, a bare `bash`. `check` refuses when any generated file
differs from what `build` would write, so a hand edit to a generated file fails. Both refuse a Copilot agent or a skill its host would reject or skip, as the standalone
validators of `scripts/agent_lint.py` find them. Where each layout is installed from is the README
section "Install".

Source front matter is one `key: value` per line. A key prefixed `copilot.` or `claude.` goes only
into that layout, without its prefix; every other key goes into both. In a source's body, the lines
between a line `<!-- copilot -->` and a line `<!-- /copilot -->` go only into the Copilot layout,
without the two marker lines; the Claude layout drops them with the markers, so it is byte for byte
what the source without them builds (`hosts`).

Every link of both layouts uses URL separators on every platform and stays relative to its generated
file (`_rewrite_links`), so it resolves both in SE's checkout and in an installed plugin's folder,
which holds the whole repository; no generated file names where SE lives (AGENTS.md "Neutral home"),
and the manifests carry no author, repository or home. A checkout with CRLF line endings (git on
Windows) builds and checks the same
layouts as an LF one: generated text is compared without its line endings (`same`).

The outside skills each role relies on are one list, `se.toml` `[roles.<role>] skills`, never the
agent's own front matter: `build` writes it into the `skills` field of that agent in every layout
whose host preloads skills (`roles` parses it; AGENTS.md "Agents and skills" owns the rule).

A draft skill (`drafts/skills/<name>/`) enters no layout unless the build setting `se.toml`
`[plugin] draft_skills` lists it by name (`draft_skills`): each listed draft is generated into
both layouts' skills folders as a skill of `src/skills` would be, so the owner can try it by name
on a real host without moving it into `src/skills`. Unset or empty, the build writes exactly what
it writes without drafts. The build refuses a listed draft that is missing, shares its name with a
skill of `src/skills`, or whose `SKILL.md` front matter lacks `disable-model-invocation: true`, so
a draft never loads by its description.

Every guidance note of the checkout's own tree (`guidance/**/<file>.md`, docs/guidance.md "Notes in
folders") is also a skill: `build` writes it into both layouts' skills folders as
`<name>/SKILL.md`, `<name>` its front matter's `name`, its front matter and body as a skill of
`src/skills` would be (`notes`). The build refuses a note that does not load (scripts/se_guidance.py
reads it), a second note of one name, and a note whose name a skill of `src/skills` or a listed draft
has. A module's tree enters no layout: its notes are its own. Where the checkout has a guidance tree,
`check` also runs the guidance check (`se_guidance.py check`, `guidance_findings`) over the checkout
and its modules, so a note it refuses, an orphan among them, fails where a stale layout fails; a
checkout without one (a copy of the generator alone) has no note of its own to check.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import posixpath
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
_marker_spec = importlib.util.spec_from_file_location("generated", Path(__file__).with_name("generated.py"))
generated_files = sys.modules.get("generated") or importlib.util.module_from_spec(_marker_spec)
if "generated" not in sys.modules:
    sys.modules["generated"] = generated_files
    _marker_spec.loader.exec_module(generated_files)
SOURCE = PurePosixPath("src")
DRAFTS = PurePosixPath("drafts/skills")
GUIDANCE = PurePosixPath("guidance")  # se_guidance.py TREE
PLUGIN = "se"
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
# The events whose hook may end with WARN, Copilot's warning: the person sees the hook's stderr and the
# run goes on (docs/copilot.md "What a session costs"). The Stop hook advises so under Copilot rather
# than refusing; every other exit code still fails open.
WARN = 2
WARN_EVENTS = ("Stop",)
# A Copilot plugin install's hooks (.github/plugin/hooks.json, which the manifest names): the same
# events, scripts and settings, each run from the plugin's own folder, `$PLUGIN_ROOT` without braces
# so no host's `${...}` expander rewrites it. Without PLUGIN_ROOT a command runs nothing, so it never
# runs a `scripts/` file of the repository it runs in; in a folder holding the repository hooks
# (COPILOT_HOOKS_FILE), SE's own checkout, it runs nothing either, as those already run its own copy.
# Each exits 0 (`plugin_hook_commands`).
# How a PowerShell hook line starts its bash script: the build setting se.toml [plugin]
# powershell_hooks (`powershell_hooks`). Unset, "bash": a bare `bash` on PATH, which Git for Windows
# does not put there. "handoff": scripts/bash.ps1, which finds the bash Git for Windows ships, started
# by Windows PowerShell with -File so no execution policy refuses it; the bash lines never change.
POWERSHELL_HOOKS = ("bash", "handoff")
HANDOFF = "scripts/bash.ps1"
HANDOFF_START = "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File"


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
# The notice that opens every Markdown file the build generates, naming its source: the marker of a
# generated file (scripts/generated.py, the guidance note generated-files-are-marked), which the
# landing guard also reads to leave the file out of authored prose. The JSON manifests carry none,
# as JSON has no comments: .gitattributes marks them.
GENERATOR = "se_plugin.py build"
NOTICE_PATTERN = re.compile(
    "^" + re.escape(generated_files.line(GENERATOR, "{source}", "html")).replace(re.escape("{source}"), r"\S+")
    + "$", re.MULTILINE)
COPILOT_HOOKS_FILE = PurePosixPath(".github/hooks/se.json")
PLUGIN_HOOKS_FILE = PurePosixPath(".github/plugin/hooks.json")
# Copilot's one plugin manifest: a plugin installed under Copilot reads this one before the Claude
# layout's .claude-plugin/plugin.json. Where it lies is the build setting se.toml [plugin]
# copilot_manifest (`copilot_manifest`): unset, "github"; "root" puts it at the repository root, the
# one place VS Code reads a Copilot-format manifest (MANIFEST_LOOKUPS). Every build writes exactly one.
COPILOT_MANIFEST_PLACES = {"github": PurePosixPath(".github/plugin/plugin.json"),
                           "root": PurePosixPath("plugin.json")}
COPILOT_MANIFEST = COPILOT_MANIFEST_PLACES["github"]
# The MCP door (README "MCP door"), declared per host: Copilot's project file, the root file
# Claude Code reads too, written only where se.toml [plugin] root_mcp is on (`root_mcp`), and the
# Claude Code manifest's mcpServers, written only where [plugin] claude_mcp is on (`claude_mcp`).
COPILOT_MCP_FILE = PurePosixPath(".github/mcp.json")
ROOT_MCP_FILE = PurePosixPath(".mcp.json")
MANIFESTS = (PurePosixPath(".claude-plugin/plugin.json"), PurePosixPath(".claude-plugin/marketplace.json"),
             COPILOT_HOOKS_FILE, PLUGIN_HOOKS_FILE, *COPILOT_MANIFEST_PLACES.values(), COPILOT_MCP_FILE, ROOT_MCP_FILE)
# Which manifest each host's plugin install picks, in the order its documentation names, each place
# with the format it reads there; documented, not measured (`manifest_pick`).
MANIFEST_LOOKUPS = {
    "copilot-cli": ((".plugin/plugin.json", "copilot"), ("plugin.json", "copilot"),
                    (".github/plugin/plugin.json", "copilot"), (".claude-plugin/plugin.json", "claude")),
    "vscode": (("plugin.json", "copilot"), (".claude-plugin/plugin.json", "claude")),
}
# The door's server: its key, and the launcher a host runs, standalone (scripts/se_mcp.sh). A project
# file names it from the project's root, the folder its host starts it in; a plugin's manifest from
# the plugin's root, whose variable a host sets in arguments only, never in the command.
MCP_SERVER = "se"
LAUNCHER = "scripts/se_mcp.sh"
COPILOT_PLUGIN_ROOT = "${PLUGIN_ROOT}"
CLAUDE_PLUGIN_ROOT = "${CLAUDE_PLUGIN_ROOT}"
# The session's folder, which Copilot expands in a server's env, so a plugin install's door can tell
# the session's project from the plugin's folder; a launcher reads it only with PLUGIN_ROOT set.
SESSION_CWD_ENV = {"SE_SESSION_CWD": "${COPILOT_SESSION_CWD}"}
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


def _sources(root: Path, drafts: list[str] = ()) -> list[PurePosixPath]:
    """Every source file: the agents and skills of `src/`, then the folders of the listed drafts."""
    base = root / SOURCE
    folders = [base / "agents", base / "skills", *(root / DRAFTS / name for name in drafts)]
    found = []
    for folder in folders:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                found.append(PurePosixPath(path.relative_to(root).as_posix()))
    return found


def _target(source: PurePosixPath, layout: Layout) -> PurePosixPath:
    """The path a source file (or a link target inside the source) has in one layout; a draft's
    lies in the layout's skills folder as a skill of `src/skills` would."""
    if source.is_relative_to(DRAFTS):
        return layout.skills / source.relative_to(DRAFTS)
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
    return posixpath.relpath(target, start)


def _rewrite_links(text: str, source: PurePosixPath, generated: PurePosixPath, layout: Layout,
                   drafts: frozenset[str] = frozenset()) -> str:
    """Each relative link as the generated file reaches its target, relative to that file; a link
    into an included draft (`drafts`) reaches its generated copy."""

    def replace(match: re.Match) -> str:
        link = match.group(2)
        if SCHEME.match(link) or link.startswith("/"):
            return match.group(0)
        resolved = _normalize((source.parent / link).as_posix())
        if (resolved.parts[:2] in (("src", "agents"), ("src", "skills"))
                or (resolved.is_relative_to(DRAFTS) and len(resolved.parts) > len(DRAFTS.parts)
                    and resolved.parts[len(DRAFTS.parts)] in drafts)):
            resolved = _target(resolved, layout)
        relative = _relative(resolved, generated.parent) + ("/" if link.endswith("/") else "")
        return match.group(1) + relative + match.group(3)

    return LINK.sub(replace, text)


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
                    role_skills: dict[str, list[RoleSkill]],
                    drafts: frozenset[str] = frozenset(),
                    generated: PurePosixPath | None = None) -> tuple[PurePosixPath, bytes]:
    """The file a source builds in one layout, at `generated` where given (a guidance note's skill),
    else at its `_target`."""
    generated = generated or _target(source, layout)
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
    body = _rewrite_links(hosts(body, source, layout, first), source, generated, layout, drafts)
    return generated, (front + notice(source) + body).encode("utf-8")


def guidance():
    """scripts/se_guidance.py, which reads and checks guidance notes, loaded when first needed, so a
    reader of the roles alone (se_start.py) needs no more scripts than before."""
    found = sys.modules.get("se_guidance")
    if found is None:
        spec = importlib.util.spec_from_file_location("se_guidance", Path(__file__).with_name("se_guidance.py"))
        found = importlib.util.module_from_spec(spec)
        sys.modules["se_guidance"] = found
        spec.loader.exec_module(found)
    return found


def notes(root: Path) -> list[tuple[PurePosixPath, str]]:
    """The checkout's own guidance notes, each its path and its name, in path order; a note that does
    not load or a second note of one name is refused, as no skill could be written from it."""
    tree = root / GUIDANCE
    if not tree.is_dir():
        return []
    se_guidance = guidance()
    found: list[tuple[PurePosixPath, str]] = []
    names: dict[str, PurePosixPath] = {}
    source = se_guidance.Source("", root, 0)
    for path in sorted(tree.rglob("*.md")):
        if not path.is_file():
            continue
        findings: list[str] = []
        note = se_guidance.read_note(source, path, findings)
        relative = PurePosixPath(path.relative_to(root).as_posix())
        if note is None:
            raise SourceError(f"{'; '.join(findings)} ({se_guidance.CHECK})")
        if note.name in names:
            raise SourceError(f"{relative}: duplicate name {note.name!r}, also {names[note.name]}; "
                              "rename one, names are unique across the trees")
        names[note.name] = relative
        found.append((relative, note.name))
    return found


def guidance_findings(root: Path) -> list[str]:
    """What the guidance check (`se_guidance.py check`) refuses in the checkout and its modules;
    nothing where the checkout has no guidance tree."""
    if not (root / GUIDANCE).is_dir():
        return []
    se_guidance = guidance()
    try:
        return se_guidance.check(se_guidance.load(root), se_guidance.page_limit())
    except se_guidance.Usage as error:
        raise SourceError(str(error)) from error


def notice(source: PurePosixPath | str) -> str:
    """The notice line that opens a Markdown file generated from `source`."""
    return generated_files.line(GENERATOR, str(source), "html") + "\n"


def _version(root: Path) -> str:
    """The plugin's version is the project's one version, `version` of `se.toml` `[project]`."""
    with (root / "se.toml").open("rb") as handle:
        version = tomllib.load(handle).get("project", {}).get("version")
    if not isinstance(version, str):
        raise SourceError(f"{root / 'se.toml'}: [project] has no version for the plugin manifest")
    return version


def _plugin_settings(root: Path) -> dict:
    """`se.toml` `[plugin]`, refused where it holds what the build cannot read."""
    with (root / "se.toml").open("rb") as handle:
        table = tomllib.load(handle).get("plugin", {})
    drafts = table.get("draft_skills", []) if isinstance(table, dict) else []
    if (not isinstance(table, dict)
            or set(table) - {"root_mcp", "claude_mcp", "copilot_manifest", "powershell_hooks", "draft_skills"}
            or not isinstance(table.get("root_mcp", False), bool)
            or not isinstance(table.get("claude_mcp", False), bool)
            or not isinstance(drafts, list) or not all(isinstance(name, str) for name in drafts)
            or table.get("copilot_manifest", "github") not in COPILOT_MANIFEST_PLACES
            or table.get("powershell_hooks", "bash") not in POWERSHELL_HOOKS):
        raise SourceError(f"{root / 'se.toml'}: [plugin] holds only `root_mcp = true|false`, "
                          "`claude_mcp = true|false`, "
                          f"`copilot_manifest = {'|'.join(map(json.dumps, COPILOT_MANIFEST_PLACES))}` and "
                          f"`powershell_hooks = {'|'.join(map(json.dumps, POWERSHELL_HOOKS))}` and "
                          '`draft_skills = ["<draft>", ...]`')
    return table


def root_mcp(root: Path) -> bool:
    """`se.toml` `[plugin] root_mcp`: whether the build writes a root `.mcp.json`, which Claude Code
    reads too; off by default."""
    return _plugin_settings(root).get("root_mcp", False)


def claude_mcp(root: Path) -> bool:
    """`se.toml` `[plugin] claude_mcp`: whether the build declares the door in the Claude Code
    manifest, `.claude-plugin/plugin.json`, run from the plugin's root; off by default."""
    return _plugin_settings(root).get("claude_mcp", False)


def copilot_manifest(root: Path) -> PurePosixPath:
    """`se.toml` `[plugin] copilot_manifest`: where Copilot's one manifest lies; unset,
    `.github/plugin/plugin.json`."""
    return COPILOT_MANIFEST_PLACES[_plugin_settings(root).get("copilot_manifest", "github")]


def powershell_hooks(root: Path) -> str:
    """`se.toml` `[plugin] powershell_hooks`: how a PowerShell hook line starts its bash script
    (POWERSHELL_HOOKS); unset, `"bash"`."""
    return _plugin_settings(root).get("powershell_hooks", "bash")


def draft_skills(root: Path) -> list[str]:
    """`se.toml` `[plugin] draft_skills`: the drafts of `drafts/skills` the build includes, by
    name, each refused where it is missing, shadows a skill of `src/skills` or may load by its
    description; unset, none."""
    names = _plugin_settings(root).get("draft_skills", [])
    path = root / "se.toml"
    for name in names:
        if names.count(name) > 1:
            raise SourceError(f"{path}: [plugin] draft_skills names {name!r} twice")
        skill = root / DRAFTS / name / "SKILL.md"
        if not agent_lint.SKILL_NAME.match(name) or not skill.is_file():
            raise SourceError(f"{path}: [plugin] draft_skills names {name!r}, but {DRAFTS}/{name}/SKILL.md "
                              "is no draft")
        if (root / SOURCE / "skills" / name).exists():
            raise SourceError(f"{path}: [plugin] draft_skills names {name!r}, which is a skill of "
                              f"{SOURCE}/skills already")
        text = skill.read_text(encoding="utf-8").replace("\r\n", "\n")
        value = agent_lint.scalar(agent_lint.fields(text).get("disable-model-invocation", ""))
        if value != "true":
            raise SourceError(f"{DRAFTS}/{name}/SKILL.md: a listed draft needs "
                              "`disable-model-invocation: true` in its front matter, so it never loads "
                              "by its description")
    return names


@dataclass(frozen=True)
class Pick:
    """The manifest one host's plugin install picks, with the format it reads it as."""

    host: str
    path: PurePosixPath
    format: str  # "copilot" or "claude"
    evidence: str = "documented"  # from the host's documentation, not measured


def manifest_pick(names, host: str) -> Pick | None:
    """Which manifest `host` (a key of MANIFEST_LOOKUPS) picks from a tree holding the files
    `names` (POSIX paths relative to the plugin root); None where it finds none. Pure."""
    present = {PurePosixPath(name) for name in names}
    for place, form in MANIFEST_LOOKUPS[host]:
        if PurePosixPath(place) in present:
            return Pick(host, PurePosixPath(place), form)
    return None


def mcp_server(launcher: str) -> dict:
    """The door's stdio server, its launcher run with bash for the project it starts in."""
    return {"type": "stdio", "command": "bash", "args": [launcher, "--root", "."]}


def _json(value: dict) -> bytes:
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def powershell_bash(script: str, setting: str = "bash", root: str = "") -> str:
    """The PowerShell words that run the bash `script` (followed by its arguments) under `setting`
    (POWERSHELL_HOOKS): a bare `bash`, or the hand-off. `root` is the PowerShell expression of the
    folder both lie in (a plugin's), empty for the working directory. Pure."""
    if setting == "bash":
        return f"bash {script}" if not root else f'bash "{root}/{script}"'
    if not root:
        return f"{HANDOFF_START} {HANDOFF} {script}"
    return f'{HANDOFF_START} "$env:PLUGIN_ROOT/{HANDOFF}" "{root}/{script}"'


def _fail_open(warn: bool) -> tuple[str, str]:
    """What follows a hook's bash and PowerShell start so it fails open; with `warn`, WARN passes
    through. Pure."""
    if not warn:
        return " || true", ""
    return f" || [ $? -ne {WARN} ] || exit {WARN}", f"; if ($LASTEXITCODE -eq {WARN}) {{ exit {WARN} }}"


def plugin_hook_commands(command: str, setting: str = "bash", warn: bool = False) -> tuple[str, str]:
    """The bash and PowerShell commands of a plugin install's hook running `command` (a script under
    `scripts/` and its arguments) from `$PLUGIN_ROOT`, guarded as PLUGIN_HOOKS_FILE says; `setting`
    is powershell_hooks'; `warn` passes WARN through (WARN_EVENTS). Pure."""
    script, _, arguments = command.partition(" ")
    tail = f" {arguments}" if arguments else ""
    guard = COPILOT_HOOKS_FILE
    bash_end, powershell_end = _fail_open(warn)
    bash = (f'if [ -n "$PLUGIN_ROOT" ] && [ ! -f {guard} ]; then '
            f'bash "$PLUGIN_ROOT/{script}"{tail}{bash_end}; fi')
    start = powershell_bash(script, setting, root="$($env:PLUGIN_ROOT.Replace([char]92,[char]47))")
    powershell = (f"if ($env:PLUGIN_ROOT -and -not (Test-Path {guard})) {{ {start}{tail}{powershell_end} }}"
                  "; exit 0")
    return bash, powershell


def hook_commands(command: str, setting: str = "bash", warn: bool = False) -> tuple[str, str]:
    """The bash and PowerShell commands of a repository hook running `command` (a script under
    `scripts/` and its arguments) from the repository's root; `setting` is powershell_hooks'; `warn`
    passes WARN through (WARN_EVENTS). Pure."""
    script, _, arguments = command.partition(" ")
    tail = f" {arguments}" if arguments else ""
    bash_end, powershell_end = _fail_open(warn)
    return f"bash {command}{bash_end}", f"{powershell_bash(script, setting)}{tail}{powershell_end}; exit 0"


def _copilot_hook(command: str, seconds: int, plugin: bool = False, setting: str = "bash",
                  warn: bool = False) -> dict:
    bash, powershell = (plugin_hook_commands if plugin else hook_commands)(command, setting, warn)
    return {"type": "command", "bash": bash, "powershell": powershell,
            "cwd": ".", "env": {"SE_HOOK_HOST": "copilot"}, "timeoutSec": seconds}


def _copilot_hooks(plugin: bool, setting: str = "bash") -> bytes:
    return _json({"version": 1, "hooks": {event: [_copilot_hook(command, seconds, plugin, setting,
                                                                event in WARN_EVENTS)]
                                         for event, (command, seconds) in COPILOT_HOOKS.items()}})


def _manifests(root: Path, copilot: bool = True) -> dict[PurePosixPath, bytes]:
    plugin = {
        "name": PLUGIN,
        "version": _version(root),
        "description": DESCRIPTION,
        "license": "MIT",
    }
    plugin["hooks"] = {
        "SessionStart": [{"hooks": [{"type": "command", "command": BOOTSTRAP}]}],
        **{event: [{"hooks": [{"type": "command", "command": kern_hook(event)}]}]
           for event in KERN_EVENTS},
    }
    if claude_mcp(root):
        plugin["mcpServers"] = {MCP_SERVER: mcp_server(f"{CLAUDE_PLUGIN_ROOT}/{LAUNCHER}")}
    marketplace = {
        "name": PLUGIN,
        "owner": {"name": "SE"},
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
        setting = powershell_hooks(root)
        files[COPILOT_HOOKS_FILE] = _copilot_hooks(plugin=False, setting=setting)
        files[PLUGIN_HOOKS_FILE] = _copilot_hooks(plugin=True, setting=setting)
    files[COPILOT_MCP_FILE] = _json({"mcpServers": {MCP_SERVER: {
        **mcp_server(LAUNCHER), "tools": ["*"], "env": SESSION_CWD_ENV}}})
    files[copilot_manifest(root)] = _json({
        "name": PLUGIN,
        "version": plugin["version"],
        "description": DESCRIPTION,
        "license": "MIT",
        "agents": f"{layout.agents}/",
        "skills": f"{layout.skills}/",
        **({"hooks": str(PLUGIN_HOOKS_FILE)} if layout.hooks else {}),
        "mcpServers": {MCP_SERVER: {**mcp_server(f"{COPILOT_PLUGIN_ROOT}/{LAUNCHER}"),
                                    "env": SESSION_CWD_ENV}},
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
    drafts = draft_skills(root)
    sources = _sources(root, drafts)
    role_skills = roles(root)
    agents = {source.stem for source in sources if source.parent == SOURCE / "agents"}
    if unknown := sorted(set(role_skills) - agents):
        raise SourceError(f"{root / 'se.toml'}: [roles.{unknown[0]}] names no agent in {SOURCE}/agents")
    for source in sources:
        for layout in LAYOUTS if copilot else LAYOUTS[1:]:
            path, data = _generated_file(source, layout, root, role_skills, frozenset(drafts))
            files[path] = data
    skills = {source.parts[2] for source in sources if source.parts[:2] == ("src", "skills")}
    for note, name in notes(root):
        if name in skills or name in drafts:
            owner = "a skill of src/skills" if name in skills else "a listed draft's"
            raise SourceError(f"{note}: the note's name {name!r} is {owner} already; rename the note")
        for layout in LAYOUTS if copilot else LAYOUTS[1:]:
            path, data = _generated_file(note, layout, root, role_skills, frozenset(drafts),
                                         layout.skills / name / "SKILL.md")
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


def same(found: bytes, want: bytes) -> bool:
    """Whether a generated file on disk holds what its source builds: text compared without its
    line endings, so a CRLF checkout (git's autocrlf on Windows) matches the LF build."""
    if found == want:
        return True
    if b"\0" in found or b"\0" in want:
        return False
    return found.replace(b"\r\n", b"\n") == want.replace(b"\r\n", b"\n")


def differences(root: Path = ROOT) -> list[str]:
    """One line per generated file that is missing, stale (hand-edited) or not generated at all."""
    want = expected(root)
    lines = []
    for path in sorted(set(want) | _existing(root)):
        if path not in want:
            lines.append(f"{path}: not generated from {SOURCE}/; remove it or add its source")
        elif not (root / path).is_file():
            lines.append(f"{path}: missing")
        elif not same((root / path).read_bytes(), want[path]):
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
        if not target.is_file() or not same(target.read_bytes(), data):
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
                        help="build: write both layouts from src/ and guidance/; check: refuse when they "
                        "differ or the guidance check refuses a note")
    parser.add_argument("--root", type=Path, default=ROOT, help="the se checkout (default: this one)")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            for path in build(args.root):
                print(f"wrote {path}")
            return 0
        lines = differences(args.root)
        refused = guidance_findings(args.root)
    except SourceError as error:
        print(f"error: se_plugin.py: {error}", file=sys.stderr)
        return 2
    for line in [*lines, *refused]:
        print(f"se_plugin.py check: {line}", file=sys.stderr)
    if lines:
        print("se_plugin.py check: generated files differ from src/ and guidance/; edit the source, "
              "then run `python scripts/se_plugin.py build`", file=sys.stderr)
    if refused:
        print(f"se_plugin.py check: the guidance check refuses the notes above ({guidance().CHECK}); "
              "fix each as it says", file=sys.stderr)
    if lines or refused:
        return 1
    print("se_plugin.py check: both layouts match src/ and guidance/, and the guidance check passes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
