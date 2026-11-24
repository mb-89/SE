# se:template se/python-module 1.0.0
"""Where each agent host reads SE from, and what each place says: pure rows for se_doctor.py --probe.

The places are host facts, the `[registrations.<surface>]` section of scripts/host-limits.toml,
whose header owns a place's fields. This module reads no file, environment or process: the
caller hands it the parsed section, each place's file content as it found it, and what its probe
saw, and gets report rows back.

- `parse` turns the section into `Place`s.
- `commands` names the commands a place's file registers SE with, as the host would run them on a
  platform (Copilot's hooks carry a `bash` and a `powershell` form), so the caller knows what to
  probe.
- A place another base hides (`hidden_by`, such as a user-level server below an installed
  plugin's) gives its `register_hidden` line while a root of that base is found.
- `rows` judges each place: missing, registering nothing, or naming a command whose interpreter
  or script does not resolve, or an MCP command that did not answer `initialize`, ends with the
  place's fix line for the platform, this checkout's launcher filled in (`fill`).

- `copilot_plugin_roots` picks, from the plugin folders found under Copilot's home and their
  manifest texts, the ones that are SE's: the roots of the base `copilot-plugin`.

A probe result, per command and the folder it starts in (keyed by `probe_key(words, cwd)`): `resolves` (the interpreter is found),
`missing` (scripts named that do not exist), `unresolved` (words naming a variable nobody fills),
and for an MCP command `answer`: "answered", "timeout" or "exited", with `detail`.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Callable, Collection, Mapping, Sequence

PLATFORMS = ("linux", "darwin", "windows")
SEEN, SILENT, NOT_MEASURED = "seen", "silent", "not measured"
PROBLEM, NOTE, OK = "problem", "note", "ok"
SCRIPT_SUFFIXES = (".sh", ".py", ".ps1", ".js", ".mjs", ".cjs", ".ts")
SPAWN_NOTE = "this probe may start the core, as a host's own spawn would"
TOKENS = ("launcher", "launcher_ps1", "checkout", "tracker")  # the placeholders of a register line


@dataclass(frozen=True)
class Place:
    surface: str
    place: str
    kind: str  # hooks | mcp
    base: str  # project | home | checkout | plugin | copilot-plugin
    files: Mapping[str, str]  # platform (or "") -> file
    finds: str
    outside: bool
    source: str
    read: str
    mark: str
    register: Mapping[str, str]  # platform (or "") -> line
    note: str = ""
    hidden_by: str = ""  # a base whose found roots hide this place's registration
    register_hidden: Mapping[str, str] = field(default_factory=dict)  # the fix line while hidden

    def file(self, platform: str) -> str:
        return self.files.get(platform) or self.files[""]

    def hidden(self, present: Collection[str]) -> bool:
        """Whether a root of the base that hides this place was found."""
        return bool(self.hidden_by) and self.hidden_by in present and bool(self.register_hidden)

    def fix(self, platform: str, fill: Mapping[str, str], present: Collection[str] = ()) -> str:
        lines = self.register_hidden if self.hidden(present) else self.register
        line = lines.get(platform) or lines[""]
        for token in TOKENS:
            line = line.replace("{" + token + "}", fill.get(token, "{" + token + "}"))
        return line


@dataclass(frozen=True)
class Seen:
    """One place as the caller found it: its file shown as the report may print it, its text (None:
    no such file), the variables its commands may name, whether it is read here at all, and the
    folder the host starts its commands in ("": the project)."""
    shown: str
    text: str | None
    variables: Mapping[str, str] = field(default_factory=dict)
    here: bool = True
    cwd: str = ""


@dataclass(frozen=True)
class Row:
    surface: str
    place: str
    file: str
    state: str
    level: str
    text: str
    fix: str | None = None


def _by_platform(row: Mapping, key: str) -> dict[str, str]:
    values = {"": str(row[key]).strip()} if key in row else {}
    values |= {p: str(row[f"{key}_{p}"]).strip() for p in PLATFORMS if f"{key}_{p}" in row}
    return values


def parse(section: Mapping) -> tuple[Place, ...]:
    """The places of a parsed `[registrations]` section, in file order."""
    places = []
    for surface, body in section.items():
        for row in body.get("places", ()):
            places.append(Place(surface=surface, place=row["place"], kind=row["kind"], base=row["base"],
                                files=_by_platform(row, "file"), finds=row["finds"], outside=bool(row["outside"]),
                                source=row.get("source", ""), read=str(row.get("read", "")),
                                mark=row.get("mark", ""), register=_by_platform(row, "register"),
                                note=row.get("note", ""), hidden_by=row.get("hidden_by", ""),
                                register_hidden=_by_platform(row, "register_hidden")))
    return tuple(places)


def key(words: Sequence[str]) -> str:
    return shlex.join(words)


def probe_key(words: Sequence[str], cwd: str = "") -> str:
    """A probe result's key: the command, and the folder it starts in where that is not the project,
    so the same words started in two folders are judged apart."""
    return key(words) if not cwd else f"{key(words)} @ {cwd}"


# Copilot CLI's plugin installs (its plugin reference, "File locations"): each plugin folder under
# its home is installed-plugins/<marketplace>/<plugin> or installed-plugins/_direct/<source>.
COPILOT_HOME_VARIABLE, COPILOT_HOME_DEFAULT = "COPILOT_HOME", ".copilot"
COPILOT_PLUGIN_FOLDERS = ("installed-plugins", "*", "*")  # the glob below Copilot's home
COPILOT_MANIFESTS = (".github/plugin/plugin.json", ".claude-plugin/plugin.json")


def copilot_home(env: Mapping[str, str], home: str) -> str:
    """Copilot's home: `$COPILOT_HOME`, or `~/.copilot` where that is unset or empty."""
    return env.get(COPILOT_HOME_VARIABLE) or str(PurePosixPath(home.replace("\\", "/")) / COPILOT_HOME_DEFAULT)


def copilot_plugin_roots(found: Mapping, name: str = "se") -> list:
    """The plugin folders that are SE's, sorted: `found` maps each folder to its manifest texts
    (None: no such file), and a folder counts where one of them is a JSON object named `name`. A
    manifest that does not parse is skipped. Reads nothing."""
    return sorted((folder for folder, texts in found.items()
                   if any((load(text) or {}).get("name") == name for text in texts)), key=str)


def _fill(word: str, variables: Mapping[str, str]) -> str:
    for name, value in variables.items():
        word = word.replace(f"${{{name}}}", value).replace(f"${name}", value)
    return word


def _hook_strings(node, platform: str) -> list[str]:
    """The command strings of a hooks tree the host runs on the platform: Claude Code's `command`,
    Copilot's `powershell` on Windows and `bash` elsewhere."""
    found: list[str] = []
    if isinstance(node, dict):
        if isinstance(node.get("command"), str):
            found.append(node["command"])
        form = "powershell" if platform == "windows" else "bash"
        if isinstance(node.get(form), str):
            found.append(node[form])
        for value in node.values():
            if isinstance(value, (dict, list)):
                found += _hook_strings(value, platform)
    elif isinstance(node, list):
        for item in node:
            found += _hook_strings(item, platform)
    return found


OPERATORS = ("||", "&&", "|", ";")


def _split(command: str) -> list[str]:
    """A command's words up to its first shell operator: what the host's shell starts first."""
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    kept = []
    for word in words:
        if word in OPERATORS:
            break
        if word.endswith(";"):
            kept.append(word[:-1])
            break
        kept.append(word)
    return [w for w in kept if w]


def load(text: str | None) -> dict | None:
    """A place's file as data; None where it is missing or no JSON object."""
    if text is None:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def commands(place: Place, text: str | None, platform: str, variables: Mapping[str, str]) -> list[list[str]]:
    """The commands the file registers SE with, as words with the variables filled in."""
    data = load(text)
    if data is None:
        return []
    if place.kind == "hooks":
        strings = [c for c in _hook_strings(data.get("hooks"), platform) if place.finds in c]
        return [[_fill(w, variables) for w in _split(c)] for c in strings]
    servers = data.get("mcpServers") or data.get("servers")
    spec = servers.get(place.finds) if isinstance(servers, dict) else None
    if not isinstance(spec, dict) or not isinstance(spec.get("command"), str):
        return []
    words = [spec["command"]] + [a for a in spec.get("args") or [] if isinstance(a, str)]
    return [[_fill(w, variables) for w in words]]


def scripts(words: Sequence[str]) -> list[str]:
    """The words of a command that name a script."""
    return [w for w in words if w.lower().endswith(SCRIPT_SUFFIXES)]


def launcher_text(path: str, home: str) -> str:
    """A launcher's path as a fix line names it: under home as `$HOME/...`, which bash and PowerShell
    both expand inside double quotes, so the line is exact and names no private path; else as is."""
    posix, base = PurePosixPath(path.replace("\\", "/")), PurePosixPath(home.replace("\\", "/"))
    try:
        rest = posix.relative_to(base).as_posix()
    except ValueError:
        return posix.as_posix()
    return "$HOME" if rest == "." else f"$HOME/{rest}"


def _row(place: Place, seen: Seen, state: str, level: str, text: str, fix: str | None = None) -> Row:
    return Row(place.surface, place.place, seen.shown, state, level, text, fix)


def _judge_command(words: Sequence[str], probe: Mapping | None, show: Callable[[str], str]) -> tuple[str, str, str]:
    """(state, level, text) of one command."""
    shown = show(key(words))
    if probe is None:
        return NOT_MEASURED, NOTE, f"{shown}: not probed"
    if not probe.get("resolves"):
        return SEEN, PROBLEM, f"{words[0]} does not resolve on this platform ({shown})"
    if probe.get("missing"):
        return SEEN, PROBLEM, f"{shown} names {', '.join(map(show, probe['missing']))}, which does not exist"
    if probe.get("unresolved"):
        return NOT_MEASURED, NOTE, f"{shown}: cannot resolve {', '.join(map(show, probe['unresolved']))}"
    answer = probe.get("answer")
    detail = f" ({show(probe['detail'])})" if probe.get("detail") else ""
    if answer is None:
        return SEEN, OK, f"{shown}: {words[0]} and its scripts resolve"
    if answer == "answered":
        return SEEN, OK, f"{shown}: answered initialize{detail}; {SPAWN_NOTE}"
    if answer == "timeout":
        return SILENT, PROBLEM, f"{shown}: no answer to initialize{detail}; {SPAWN_NOTE}"
    return SEEN, PROBLEM, f"{shown}: exited without answering initialize{detail}; {SPAWN_NOTE}"


def rows(entries: Sequence[tuple[Place, Seen]], probes: Mapping[str, Mapping], platform: str,
         fill: Mapping[str, str], show: Callable[[str], str] = str, present: Collection[str] = ()) -> list[Row]:
    """One row per place found or missing, one per command it registers SE with; a missing or
    broken one carries its fix line for the platform: its `register_hidden` line where `present`, the
    bases with a root found, holds the base that hides it."""
    out: list[Row] = []
    for place, seen in entries:
        fix = place.fix(platform, fill, present)
        label = f"{place.surface} {place.place} {seen.shown}"
        if not seen.here:
            out.append(_row(place, seen, NOT_MEASURED, NOTE,
                            f"{label}: read only in SE's own checkout, not in this project"))
            continue
        if seen.text is None:
            out.append(_row(place, seen, SEEN, NOTE, f"{label}: not registered (no such file)", fix))
            continue
        if load(seen.text) is None:
            out.append(_row(place, seen, SEEN, PROBLEM, f"{label}: not a JSON object", fix))
            continue
        found = commands(place, seen.text, platform, seen.variables)
        if not found:
            what = f"no server {place.finds}" if place.kind == "mcp" else f"no command naming {place.finds}"
            out.append(_row(place, seen, SEEN, NOTE, f"{label}: not registered ({what})", fix))
            continue
        for words in found:
            state, level, text = _judge_command(words, probes.get(probe_key(words, seen.cwd)), show)
            out.append(_row(place, seen, state, level, f"{label}: {text}", fix if level == PROBLEM else None))
    return out
