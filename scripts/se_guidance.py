#!/usr/bin/env python3
"""Guidance: SE reads the guidance trees of a project and of its modules, resolves them for a
template or a set of tags, generates the tool files they implement, and checks them, as
docs/guidance.md designs ("Notes in folders", "Resolution", "Guidance without a template",
"Implementations and projections"). It is the command component `guidance`.

**Trees.** A guidance tree is the folder `guidance/` at the root of a source: each module the
project's se.toml declares, in its order, at its folder on this machine (se_modules.py
`module_dirs`), then the project itself. A module without the folder, or not placed, has none.

**Notes.** Every `*.md` file of a tree is one note. Its front matter, between `---` lines, holds
one `key: value` a line, the value plain, quoted (`'...'` or `"..."`) or a list (`[a, b]`):

- `name` and `description`, the two keys a skill needs, both required;
- `tags`, a list, optional: tags beside those its folders give;
- `overrides`, optional: the name of the note it replaces (Resolution, below).

No other key loads. Its body may carry implementations of itself for other tools, one per target:
a fenced block whose info string is `implements <path>`, the path a file relative to the
project's root, of a kind whose lines `#` comments (COMMENTS), and the block the text that file
gets from the note. A note's depth is the number of folders between it and `guidance/`; its tags
are every folder name on that way and its own `tags`, as one set. A tag and a name are lowercase
words of letters and digits joined by single dashes (TAG).

**Templates.** Each template note `templates/<name>.md` of a source is the template `<name>`
with the tags of its front matter's `tags` list (none where it sets none), read as
`scripts/templates.py` reads the note (`templates.note_data`); a project's template replaces a
module's of the same name.

**Resolution.** A template gets every note whose tags it carries all of. A tag query
(`--tags a,b`) gets every note that carries all the asked tags, and every note at depth 0. Where a
note of the resolution names another in `overrides`, the named note is dropped from it; the
overriding note prints at its own place. The notes print by depth, lowest first; at equal depth by
the number of tags, fewest first; then the modules' notes before the project's, in se.toml's
order; then by path.

**Projections.** Each file the notes implement gets one generated part: a header line that says
`se_guidance.py project` generates it from the notes it names, every implementation of that file
in the notes' order (Resolution, below), and an end line. Where the file holds the part, the part
is replaced; where it holds none, the part follows the file's own text; where there is no file,
the part is the file. Nothing else of the file changes, so a project keeps its own settings beside
the generated ones (`pyproject.toml` beside `[tool.ruff]`).

**The check** refuses, each finding naming the note's file and the remedy:

- a note whose front matter is missing or not `key: value` lines, or lacks `name` or
  `description`;
- a key other than the four above (unknown key);
- a name or a tag that breaks TAG, a folder name among them;
- a second note of one name, in any tree, naming both files (duplicate name);
- a note that reaches no template (orphan), naming its tags;
- an override of a note no tree holds, of itself, of a note whose tags it does not carry all
  of, a module's override of a project's note, or an override in a cycle (bad override);
- a note over a quarter of kern's page limit (`PageLimit` in kern's `mcp/page.go`, read from the
  kern clone se pins), naming its size;
- a template whose `tags` is no list of tags;
- an implementation of a path outside the project or in `guidance/`, of a file of unknown
  comments, or a second one of one path in a note;
- a generated file that does not match its notes, edited by hand or behind a changed note, naming
  `se_guidance.py project`; for a `.toml` file, a projection that is no TOML.

**Delivery** (`delivered`, which `collect` and the templates tool's `draft` and `fill` print
through, scripts/se_templates.py):

- *Once per session.* `--session ID` names the session (letters, digits, `.`, `_`, `-`); its
  record is the file `.se/.runtime/sessions/<ID>/guidance.yaml` under the project, one
  `<name>: "<sha256 of the note's text>"` a line (RECORD_FILE). A note the record holds with that
  digest is not printed again: a run of them is the line `already printed this session: <name>,
  <name>` where they would stand, and the first line counts them. Without `--session` nothing is
  kept and every note prints.
- *Pages.* An answer stays within kern's page limit (above): pages break between notes, never
  inside one, each full to the limit less PAGE_RESERVE, and the template comes on the last page
  (on a page of its own where it does not fit beside the last notes). A page that is not the last
  ends with a line saying how many follow and how to ask for the next: in a session, the same
  call again, as the record now holds the page's notes; without one, the same call with
  `--page <next>`. A later page opens with the heading and its number. Each page's notes enter the
  record as it is printed. `--page` with `--session` is refused.

**Commands.** `collect` and `check` only read, but for a session's record; `project` writes only
the generated files, `pin` only its table. None calls GitHub or starts a model.

- `se_guidance.py collect (--template NAME | --tags A,B) [--session ID] [--page N] [--json]
  [--root ROOT]` prints the resolution as Delivery (below) pages it: a line naming what was
  resolved and how many notes, then each note as a `##` heading of its name, a line with its file,
  depth and tags, and its text. `--json` prints the list of notes instead (`name`, `path`,
  `depth`, `tags`), whole, keeping no record. An unknown template is answered with the list of
  templates, exit code 2; a tag no note carries is named, with the tags that exist, before the
  rest. A note that does not load is left out and named on stderr.
- `se_guidance.py check [--root ROOT]` prints every finding, one a line, exit code 1, or `passes:
  <n> notes, <m> templates`, exit code 0.

- `se_guidance.py project [--root ROOT]` writes each generated file that does not match its
  notes, printing `wrote <path>` or `<path>: up to date`, exit code 0.
- `se_guidance.py pin [--root ROOT]` writes `tests/guidance-pins.yaml` (PINS): every template, by
  name, with the names of the notes it gets in order, a YAML list each, printing `wrote <path>: <n>
  templates` or `<path>: up to date`, exit code 0. `pin_differences` names each template whose
  resolution differs from it; SE's test compares every resolution with it
  (docs/guidance.md "Resolution").

`--root` is the project (default: the folder holding se.toml at or above the working directory,
else the working directory). Exit code 2 is a usage or setup error, named.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
SE_ROOT = HERE.parent
TREE = "guidance"
TEMPLATES = "templates"
#: A tag, a folder name and a note's name: lowercase words of letters and digits joined by dashes.
TAG = re.compile(r"\A[a-z0-9]+(?:-[a-z0-9]+)*\Z")
#: The keys of a note's front matter: a skill's two, then the two of guidance, never a third.
SKILL_KEYS = ("name", "description")
KEYS = (*SKILL_KEYS, "tags", "overrides")
#: Where kern declares its page limit, in the kern clone se pins, and how.
PAGE_FILE = Path("mcp") / "page.go"
PAGE_LIMIT = re.compile(r"^const PageLimit = (\d+)$", re.MULTILINE)
CHECK = "se_guidance.py check"
PROJECT = "se_guidance.py project"
#: A fence that opens a note's implementation: ```implements <path>.
IMPLEMENTS = re.compile(r"\A(`{3,}|~{3,})implements[ \t]+(\S+)[ \t]*\Z")
FENCE = re.compile(r"\A(`{3,}|~{3,})")
#: The comment that starts a line in the files a projection may write, by suffix or by name.
COMMENTS = {**dict.fromkeys((".toml", ".yaml", ".yml", ".cfg", ".ini", ".conf", ".sh", ".py",
                             ".properties"), "#"),
            **dict.fromkeys((".gitignore", ".gitattributes", ".editorconfig", "Makefile",
                             "Dockerfile"), "#")}
BEGIN = ("{comment} Generated by `se_guidance.py project` from the guidance notes {names}; edit "
         "them, never this part.")
BEGIN_START = "{comment} Generated by `se_guidance.py project` "
END = "{comment} End of what `se_guidance.py project` generates."


def sibling(name: str):
    """The script `<name>.py` beside this one, imported when a command needs it."""
    here = str(HERE)
    if here not in sys.path:
        sys.path.append(here)
    return importlib.import_module(name)


class Usage(Exception):
    """A usage or setup error: its message is the answer, exit code 2."""


@dataclass(frozen=True)
class Source:
    """One guidance tree's owner: a module (`module` its name) or the project (`module` "")."""

    module: str
    root: Path
    rank: int

    def where(self, relative: str) -> str:
        return f"{self.module}:{relative}" if self.module else relative


@dataclass(frozen=True)
class Note:
    name: str
    description: str
    tags: frozenset[str]
    folders: tuple[str, ...]
    own_tags: tuple[str, ...]
    overrides: str
    path: str  # relative to its source's root, as posix, `guidance/...`
    source: Source
    size: int
    body: str
    #: Its implementations, each a project-relative path and the text the note gives that file.
    implementations: tuple[tuple[str, str], ...] = ()

    @property
    def depth(self) -> int:
        return len(self.folders)

    @property
    def where(self) -> str:
        return self.source.where(self.path)

    def order(self) -> tuple:
        return (self.depth, len(self.tags), self.source.rank, self.path)


@dataclass(frozen=True)
class Template:
    name: str
    tags: frozenset[str]
    where: str


@dataclass
class Loaded:
    """What the trees hold: the notes that loaded, the templates, and every finding of loading."""

    notes: list[Note]
    templates: dict[str, Template]
    findings: list[str]
    root: Path


# Reading.

def sources(root: Path) -> list[Source]:
    """The modules se.toml declares, in its order, then the project; each once."""
    modules = sibling("se_modules")
    try:
        found = modules.module_dirs(root, modules.load_local(modules.default_local_config()))
    except modules.ModuleError as error:
        raise Usage(f"se_guidance.py: {error}; fix se.toml (README \"Modules\")") from error
    listed, seen = [], {root.resolve()}
    for name, folder in found:
        if folder.resolve() not in seen:
            seen.add(folder.resolve())
            listed.append(Source(name, folder, len(listed)))
    return [*listed, Source("", root, len(listed))]


def scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        inner = value[1:-1]
        return inner.replace("''", "'") if value[0] == "'" else inner
    return value


def front_matter(text: str) -> tuple[dict[str, str], str] | str:
    """The note's keys with their raw values and its body, or what is wrong with its head."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return "has no front matter; start it with a --- line, name: and description:, and ---"
    for end in range(1, len(lines)):
        if lines[end].strip() == "---":
            break
    else:
        return "has no closing --- under its front matter"
    keys: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep or not key.strip() or key != key.strip():
            return f"front matter line is not `key: value`: {line.strip()}"
        if key in keys:
            return f"front matter names {key} twice; keep one"
        keys[key] = value.strip()
    return keys, "".join(lines[end + 1:]).lstrip("\n")


def tag_list(value: str) -> list[str] | None:
    """A front-matter list `[a, b]` as its items; None where it is no list."""
    value = value.strip()
    if not (value.startswith("[") and value.endswith("]")):
        return None
    inner = value[1:-1].strip()
    return [scalar(item) for item in inner.split(",")] if inner else []


def comment_of(path: str) -> str | None:
    name = Path(path).name
    return COMMENTS.get(name) or COMMENTS.get(Path(path).suffix)


def implementations(body: str, where: str, findings: list[str]) -> tuple[tuple[str, str], ...]:
    """The note's ```implements <path> blocks, one per path, each checked; a fence of the same
    character and at least its length closes one."""
    found: dict[str, str] = {}
    lines, index = body.splitlines(keepends=True), 0
    while index < len(lines):
        opening = FENCE.match(lines[index].strip())
        if not opening:
            index += 1
            continue
        fence, implements = opening[1], IMPLEMENTS.match(lines[index].strip())
        end = index + 1
        while end < len(lines) and not (lines[end].strip().startswith(fence[0] * len(fence))
                                        and not lines[end].strip().strip(fence[0])):
            end += 1
        if implements:
            target, text = implements[2], "".join(lines[index + 1:end])
            posix = Path(target).as_posix()
            if Path(target).is_absolute() or ".." in Path(target).parts or posix.startswith(
                    f"{TREE}/"):
                findings.append(f"{where}: implements {target!r}, no path inside the project; "
                                "name a file relative to the project's root")
            elif comment_of(posix) is None:
                findings.append(f"{where}: implements {posix}, a file whose comment syntax "
                                "the guidance command does not know, so it cannot say it is "
                                "generated; use a file of #-comments")
            elif posix in found:
                findings.append(f"{where}: implements {posix} twice; one implementation per "
                                "target")
            else:
                found[posix] = text if not text or text.endswith("\n") else text + "\n"
        index = end + 1
    return tuple(found.items())


def read_note(source: Source, path: Path, findings: list[str]) -> Note | None:
    relative = path.relative_to(source.root).as_posix()
    where = source.where(relative)
    folders = tuple(path.relative_to(source.root / TREE).parts[:-1])
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        findings.append(f"{where}: is not UTF-8 text; save it as UTF-8")
        return None
    parsed = front_matter(text)
    if isinstance(parsed, str):
        findings.append(f"{where}: {parsed}")
        return None
    keys, body = parsed
    loads = True
    unknown = [key for key in keys if key not in KEYS]
    if unknown:
        findings.append(f"{where}: unknown key {', '.join(unknown)}; a note has only "
                        f"{', '.join(KEYS)} (docs/guidance.md \"Notes in folders\")")
    for key in SKILL_KEYS:
        if not scalar(keys.get(key, "")):
            findings.append(f"{where}: no {key}; a note is also a skill and needs name and "
                            "description")
            loads = False
    name = scalar(keys.get("name", ""))
    if name and not TAG.match(name):
        findings.append(f"{where}: name {name!r} is no lowercase words joined by dashes; "
                        "rename it")
    own: list[str] = []
    if "tags" in keys:
        listed = tag_list(keys["tags"])
        if listed is None:
            findings.append(f"{where}: tags is no list; write tags: [a, b]")
        else:
            own = listed
    for folder in folders:
        if not TAG.match(folder):
            findings.append(f"{where}: folder {folder!r} is no tag, lowercase words joined by "
                            "dashes; rename the folder")
    for tag in own:
        if not TAG.match(tag):
            findings.append(f"{where}: tag {tag!r} is no lowercase words joined by dashes; "
                            "respell it")
    implemented = implementations(body, where, findings)
    if not loads:
        return None
    return Note(name, scalar(keys["description"]), frozenset((*folders, *own)), folders,
                tuple(own), scalar(keys.get("overrides", "")), relative, source, len(data), body,
                implemented)


def read_templates(source: Source, templates: dict[str, Template], findings: list[str]) -> None:
    folder = source.root / TEMPLATES
    if not folder.is_dir():
        return
    engine = sibling("templates")
    for path in sorted(folder.glob(f"*{engine.TEMPLATE_SUFFIX}")):
        if path.name.endswith(engine.OVERLAY_SUFFIX):
            continue  # read with its template, whose tags it adds to
        where = source.where(path.relative_to(source.root).as_posix())
        try:
            data = engine.note_data(path.read_text(encoding="utf-8"), where)
            overlay = path.with_name(path.name.removesuffix(engine.TEMPLATE_SUFFIX) + engine.OVERLAY_SUFFIX)
            if overlay.is_file() and isinstance(data.setdefault("tags", []), list):
                data["tags"] += engine.overlay_tags(overlay.read_text(encoding="utf-8"),
                                                    source.where(overlay.relative_to(source.root).as_posix()))
        except UnicodeDecodeError as error:
            findings.append(f"{where}: not UTF-8 ({error}); fix the template")
            continue
        except engine.TemplateError as error:
            findings.append(f"{error}")
            continue
        tags = data.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(t, str) and TAG.match(t) for t in tags):
            findings.append(f"{where}: tags is no list of tags, lowercase words joined by "
                            "dashes; fix the template's tags")
            tags = []
        name = data.get("name") if isinstance(data.get("name"), str) else path.stem
        templates[name] = Template(name, frozenset(tags), where)


def load(root: Path) -> Loaded:
    """Every note of every tree, sorted, every template, and the findings of reading them."""
    notes: list[Note] = []
    templates: dict[str, Template] = {}
    findings: list[str] = []
    for source in sources(root):
        tree = source.root / TREE
        if tree.is_dir():
            for path in sorted(tree.rglob("*.md")):
                if path.is_file():
                    note = read_note(source, path, findings)
                    if note is not None:
                        notes.append(note)
        read_templates(source, templates, findings)
    return Loaded(sorted(notes, key=Note.order), templates, findings, root)


# Resolution.

def resolved(chosen: list[Note]) -> list[Note]:
    """`chosen` without the notes an override among them names, in the documented order."""
    dropped = {note.overrides for note in chosen if note.overrides}
    return sorted((note for note in chosen if note.name not in dropped), key=Note.order)


def for_template(notes: list[Note], template: Template) -> list[Note]:
    return resolved([note for note in notes if note.tags <= template.tags])


def for_tags(notes: list[Note], tags: frozenset[str]) -> list[Note]:
    return resolved([note for note in notes if tags <= note.tags or note.depth == 0])


# Projections.

@dataclass(frozen=True)
class Projection:
    """One tool file the notes implement: its path in the project and the part they generate."""

    path: str
    names: tuple[str, ...]
    part: str

    def applied(self, current: str | None) -> str:
        """The file's text with the generated part in place: replacing the part it holds, after
        the file's own text where it holds none, or alone where there is no file."""
        comment = comment_of(self.path)
        lines = (current or "").splitlines(keepends=True)
        start = BEGIN_START.format(comment=comment)
        end_line = END.format(comment=comment)
        begin = next((i for i, line in enumerate(lines) if line.startswith(start)), None)
        if begin is not None:
            end = next((i for i in range(begin, len(lines)) if lines[i].rstrip("\r\n") == end_line),
                       len(lines) - 1)
            return "".join([*lines[:begin], self.part, *lines[end + 1:]])
        own = (current or "").rstrip("\n")
        return f"{own}\n\n{self.part}" if own else self.part


def projections(notes: list[Note]) -> list[Projection]:
    """Each file the notes implement, its part every implementation of it in the notes' order."""
    by_path: dict[str, list[tuple[str, str]]] = {}
    for note in notes:
        for path, text in note.implementations:
            by_path.setdefault(path, []).append((note.name, text))
    found = []
    for path, parts in sorted(by_path.items()):
        comment, names = comment_of(path), tuple(sorted(name for name, _ in parts))
        part = "".join([BEGIN.format(comment=comment, names=", ".join(names)) + "\n",
                        *(text for _, text in parts), END.format(comment=comment) + "\n"])
        found.append(Projection(path, names, part))
    return found


def current_text(root: Path, path: str) -> str | None:
    file = root / path
    return file.read_text(encoding="utf-8") if file.is_file() else None


def projection_findings(loaded: Loaded) -> list[str]:
    findings = []
    for projection in projections(loaded.notes):
        current = current_text(loaded.root, projection.path)
        expected = projection.applied(current)
        if projection.path.endswith(".toml"):
            try:
                tomllib.loads(expected)
            except tomllib.TOMLDecodeError as error:
                findings.append(f"{projection.path}: its projection is not TOML ({error}); fix "
                                f"the implementations of {', '.join(projection.names)}")
                continue
        if current != expected:
            findings.append(f"{projection.path}: does not match its notes "
                            f"({', '.join(projection.names)}); run `{PROJECT}`, never edit it "
                            "by hand")
    return findings


# Pins.

#: The committed table of every template's resolution, under the project's root.
PINS = Path("tests") / "guidance-pins.yaml"
PIN = "se_guidance.py pin"
PINS_HEAD = ("# Generated by `se_guidance.py pin`: each template with the guidance notes it gets, in "
             "order\n# (docs/guidance.md \"Resolution\"). A change that moves a note into or out "
             "of a template\n# rewrites it with that command; its diff is what a reviewer reads.\n")


def pins(loaded: Loaded) -> dict[str, list[str]]:
    """Each template, by name, with the names of the notes it resolves, in order."""
    return {name: [note.name for note in for_template(loaded.notes, template)]
            for name, template in sorted(loaded.templates.items())}


def yaml_word(word: str) -> str:
    """A template's or a note's name as a YAML scalar: plain, quoted where a reader may take it
    for something else than a string."""
    engine = sibling("templates")
    if engine.YAML_INT.match(word) or engine.YAML_AMBIGUOUS.match(word):
        return json.dumps(word)
    return word


def pins_text(loaded: Loaded) -> str:
    """The table PINS holds for `loaded`: one key a template, its notes a list below it."""
    parts = [PINS_HEAD]
    for name, notes in pins(loaded).items():
        parts.append(f"{yaml_word(name)}:" + ("".join(f"\n  - {yaml_word(note)}" for note in notes)
                                               if notes else " []") + "\n")
    return "".join(parts)


def pin_differences(loaded: Loaded) -> list[str]:
    """Each template whose resolution differs from the committed table, naming both and the
    command that rewrites it; the table missing or not reading is one finding."""
    path = loaded.root / PINS
    engine = sibling("templates")
    try:
        pinned = engine.front_data(path.read_text(encoding="utf-8"), PINS.as_posix(), 1)
    except OSError:
        return [f"{PINS.as_posix()}: missing; run `{PIN}`"]
    except engine.TemplateError as error:
        return [f"{error}; run `{PIN}`"]
    found = []
    resolved_now = pins(loaded)
    for name in sorted(set(pinned) | set(resolved_now)):
        now, then = resolved_now.get(name), pinned.get(name)
        if now == then:
            continue
        said = ("not pinned" if then is None else f"pinned {', '.join(map(str, then)) or 'none'}")
        gets = ("no such template" if now is None else f"resolves {', '.join(now) or 'none'}")
        found.append(f"{PINS.as_posix()}: {name}: {said}, {gets}; run `{PIN}` and review the diff")
    return found


# The check.

def page_limit() -> int:
    """kern's page limit, from the kern clone se pins (se_modules.py `kern_dir`)."""
    page = sibling("se_modules").kern_dir(SE_ROOT) / PAGE_FILE
    try:
        found = PAGE_LIMIT.search(page.read_text(encoding="utf-8"))
    except OSError:
        found = None
    if found is None:
        raise Usage(f"se_guidance.py: no `const PageLimit` in {page}; place kern at its pin with "
                    "`uv run python scripts/se_modules.py sync kern`")
    return int(found[1])


def check(loaded: Loaded, limit: int) -> list[str]:
    """Every finding of the trees: those of reading, then each rule docs/guidance.md sets."""
    findings = list(loaded.findings)
    by_name: dict[str, Note] = {}
    for note in loaded.notes:
        first = by_name.setdefault(note.name, note)
        if first is not note:
            findings.append(f"{note.where}: duplicate name {note.name!r}, also {first.where}; "
                            "rename one, names are unique across the trees")
    templates = list(loaded.templates.values())
    for note in loaded.notes:
        if not any(note.tags <= template.tags for template in templates):
            tags = ", ".join(sorted(note.tags)) or "none"
            findings.append(f"{note.where}: orphan, no template carries all its tags ({tags}); "
                            "fix its tags or delete it")
        if note.size > limit // 4:
            findings.append(f"{note.where}: {note.size} bytes, over a quarter of kern's page "
                            f"limit ({limit // 4} of {limit}); split it into more specific notes")
    for note in loaded.notes:
        if not note.overrides:
            continue
        target = by_name.get(note.overrides)
        bad = f"{note.where}: bad override of {note.overrides!r}"
        if note.overrides == note.name:
            findings.append(f"{bad}: a note cannot override itself; drop overrides")
        elif target is None:
            findings.append(f"{bad}: no tree holds that note; name an existing note")
        elif not target.tags <= note.tags:
            missing = ", ".join(sorted(target.tags - note.tags))
            findings.append(f"{bad} ({target.where}): it lacks its tags {missing}; only a more "
                            "specific note may override")
        elif note.source.module and not target.source.module:
            findings.append(f"{bad} ({target.where}): a module never overrides the project")
        else:
            chain, current = [note.name, target.name], target
            while current is not None and current.overrides:
                if current.overrides in chain:
                    if current.overrides == note.name:
                        findings.append(f"{bad}: the overrides form a cycle "
                                        f"({' -> '.join([*chain, note.name])}); break it")
                    break
                chain.append(current.overrides)
                current = by_name.get(current.overrides)
    return findings + projection_findings(loaded)


# Delivery.

#: The bytes of a page kept for the line that says how many pages follow, and the continued
#: heading: a page's notes and template fill the page limit less this.
PAGE_RESERVE = 400
#: A session's id, as a file name may hold it.
SESSION = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
#: Without a core, a session's record is this file under the project's runtime folder.
RECORD_FOLDER = Path(".se") / ".runtime" / "sessions"
RECORD_FILE = "guidance.yaml"
RECORD_HEAD = ("# The guidance notes printed to this session by se_guidance.py, each name with the "
               "sha256 of its text.\n# Delete the file and the next call prints every note again.\n")


def digest(note: Note) -> str:
    """The digest of a note's text: a note whose text changed prints again."""
    return hashlib.sha256(note.body.encode("utf-8")).hexdigest()


@dataclass
class Record:
    """The notes already printed to one session, by name and digest; without a session none, and
    nothing is kept (docs/guidance.md "Once per session")."""

    path: Path | None
    seen: dict[str, str]

    @classmethod
    def of(cls, root: Path, session: str | None) -> "Record":
        if session is None:
            return cls(None, {})
        if not SESSION.match(session):
            raise Usage(f"se_guidance.py: --session {session!r} is no session id; give letters, "
                        "digits, dots, dashes and underscores")
        path = root / RECORD_FOLDER / session / RECORD_FILE
        if not path.is_file():
            return cls(path, {})
        engine = sibling("templates")
        try:
            data = engine.front_data(path.read_text(encoding="utf-8"), path.as_posix(), 1)
        except (OSError, UnicodeDecodeError, engine.TemplateError) as error:
            raise Usage(f"se_guidance.py: the session record {path.as_posix()} does not read "
                        f"({error}); delete it, and the next call prints every note again") from error
        return cls(path, {str(name): str(value) for name, value in data.items()})

    def holds(self, note: Note) -> bool:
        return self.seen.get(note.name) == digest(note)

    def add(self, notes: list[Note]) -> None:
        """Record `notes` as printed, where a session keeps a record."""
        if self.path is None or not notes:
            return
        self.seen.update((note.name, digest(note)) for note in notes)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(RECORD_HEAD + "".join(f"{name}: {json.dumps(value)}\n"
                                                   for name, value in sorted(self.seen.items())),
                             encoding="utf-8", newline="\n")


def note_text(note: Note) -> str:
    tags = ", ".join(sorted(note.tags)) or "none"
    return (f"\n## {note.name}\n\n`{note.where}` · depth {note.depth} · tags: {tags}\n\n"
            f"{note.body.rstrip()}\n")


def blocks(notes: list[Note], record: Record) -> list[tuple[str, list[Note]]]:
    """Each note's text with the note, in order; a run of notes the record holds is one line
    that names them where they would stand."""
    found: list[tuple[str, list[Note]]] = []
    named: list[str] = []
    for note in notes:
        if record.holds(note):
            named.append(note.name)
            continue
        if named:
            found.append((f"\nalready printed this session: {', '.join(named)}\n", []))
            named = []
        found.append((note_text(note), [note]))
    if named:
        found.append((f"\nalready printed this session: {', '.join(named)}\n", []))
    return found


def size(text: str) -> int:
    return len(text.encode("utf-8"))


def paginated(head: str, found: list[tuple[str, list[Note]]], tail: str,
              limit: int) -> list[tuple[str, list[Note]]]:
    """The pages of an answer: `head`, then the blocks, a page breaking between them where the
    next would pass the limit (less PAGE_RESERVE), and `tail` on the last page."""
    budget = limit - PAGE_RESERVE
    pages: list[tuple[str, list[Note]]] = []
    text, notes, filled = head, [], False
    for block, its in found:
        if filled and size(text + block) > budget:
            pages.append((text, notes))
            text, notes = "", []
        text, notes, filled = text + block, notes + its, True
    if tail and filled and size(text + tail) > budget:
        pages.append((text, notes))
        text, notes = "", []
    pages.append((text + tail, notes))
    return pages


def delivered(root: Path, notes: list[Note], heading: str, *, session: str | None = None,
              page: int = 1, tail: str = "", before: str = "", limit: int | None = None) -> str:
    """One page of the answer that delivers `notes` under `heading`, then `tail` (a template) on
    the last page; the notes of the page printed enter the session's record (docs/guidance.md
    "Delivery"). `before` opens the first page. With a session the next call with the same
    arguments answers the next page, as the record holds this one's notes; without one, `page`
    names the page."""
    if page < 1:
        raise Usage(f"se_guidance.py: --page {page}; pages count from 1")
    if session is not None and page != 1:
        raise Usage("se_guidance.py: --page is for a call without --session; with a session, "
                    "call again with the same arguments for the next page")
    record = Record.of(root, session)
    found = blocks(notes, record)
    named = sum(record.holds(note) for note in notes)
    already = f"; {named} already printed this session" if named else ""
    head = f"{before}{heading}: {plural(len(notes), 'note')}, general before specific{already}.\n"
    pages = paginated(head, found, tail, limit or page_limit())
    if page > len(pages):
        raise Usage(f"se_guidance.py: --page {page}, but the answer has {plural(len(pages), 'page')}")
    text, printed_notes = pages[page - 1]
    if page > 1:
        text = f"{heading}, page {page} of {len(pages)}.\n{text}"
    rest = len(pages) - page
    template = ", the template on the last" if tail else ""
    if rest and session is not None:
        text += (f"\n[{plural(rest, 'more page')} follow{'s' if rest == 1 else ''}{template}: call "
                 "again with the same arguments for the next; this session's record now holds "
                 "the notes above.]\n")
    elif rest:
        text += (f"\n[page {page} of {len(pages)}{template}: call again with the same arguments "
                 f"and --page {page + 1} for the next.]\n")
    record.add(printed_notes)
    return text


# Commands.

def project_root(given: Path | None) -> Path:
    if given is not None:
        if not given.is_dir():
            raise Usage(f"se_guidance.py: --root {given} is no folder; name the project's folder")
        return given
    start = Path.cwd()
    for folder in (start, *start.parents):
        if (folder / "se.toml").is_file():
            return folder
    return start


def tags_given(text: str) -> frozenset[str]:
    tags = frozenset(part.strip() for part in text.split(",") if part.strip())
    if not tags:
        raise Usage("se_guidance.py collect: --tags names no tag; give one or more, a,b")
    return tags


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def run_collect(options: argparse.Namespace) -> int:
    root = project_root(options.root)
    loaded = load(root)
    for finding in loaded.findings:
        print(f"left out: {finding} ({CHECK})", file=sys.stderr)
    before = ""
    if options.template is not None:
        template = loaded.templates.get(options.template)
        if template is None:
            names = ", ".join(sorted(loaded.templates)) or "none"
            raise Usage(f"se_guidance.py collect: no template {options.template!r}; the "
                        f"templates are: {names}")
        notes = for_template(loaded.notes, template)
        heading = f"Guidance for the template {template.name}"
    else:
        asked = tags_given(options.tags)
        notes = for_tags(loaded.notes, asked)
        heading = f"Guidance for the tags {', '.join(sorted(asked))}"
        carried = frozenset().union(*(note.tags for note in loaded.notes))
        unknown = sorted(asked - carried)
        if unknown:
            before = (f"No note carries the tag{'' if len(unknown) == 1 else 's'} "
                      f"{', '.join(unknown)}; the tags are: {', '.join(sorted(carried)) or 'none'}.\n\n")
    if options.json:
        if options.session is not None or options.page != 1:
            raise Usage("se_guidance.py collect: --json lists every note and keeps no record; "
                        "drop --session and --page")
        print(json.dumps([{"name": note.name, "path": note.where, "depth": note.depth,
                           "tags": sorted(note.tags)} for note in notes], indent=2))
        return 0
    print(delivered(root, notes, heading, session=options.session, page=options.page,
                    before=before), end="")
    return 0


def run_check(options: argparse.Namespace) -> int:
    loaded = load(project_root(options.root))
    findings = check(loaded, page_limit())
    if findings:
        print("\n".join(findings))
        return 1
    print(f"passes: {plural(len(loaded.notes), 'note')}, "
          f"{plural(len(loaded.templates), 'template')}")
    return 0


def run_pin(options: argparse.Namespace) -> int:
    loaded = load(project_root(options.root))
    for finding in loaded.findings:
        print(f"left out: {finding} ({CHECK})", file=sys.stderr)
    file, text = loaded.root / PINS, pins_text(loaded)
    if file.is_file() and file.read_text(encoding="utf-8") == text:
        print(f"{PINS.as_posix()}: up to date")
        return 0
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {PINS.as_posix()}: {plural(len(loaded.templates), 'template')}")
    return 0


def run_project(options: argparse.Namespace) -> int:
    loaded = load(project_root(options.root))
    for finding in loaded.findings:
        print(f"left out: {finding} ({CHECK})", file=sys.stderr)
    for projection in projections(loaded.notes):
        current = current_text(loaded.root, projection.path)
        expected = projection.applied(current)
        if current == expected:
            print(f"{projection.path}: up to date")
            continue
        file = loaded.root / projection.path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(expected, encoding="utf-8", newline="\n")
        print(f"wrote {projection.path}")
    return 0


#: se_guidance.py's commands as one kern component (README "Commands as components"); each
#: command's usage and help come from make_parser.
COMPONENTS = (sibling("se_components").Group(
    "guidance", "Guidance",
    "SE's guidance: collect resolves the guidance trees of the project and its modules for a "
    "template or a set of tags, general before specific; project writes the tool files the notes "
    "implement; pin writes every template's resolution to tests/guidance-pins.yaml; and check "
    "finds what docs/guidance.md refuses in them.",
    ("collect", "check", "project", "pin")),)
#: The commands that go through kern where it runs (se_components.routed): both only read.
INTERACTIVE_COMMANDS = frozenset({"collect", "check"})
#: The same two, each with when an agent uses it: kern's MCP door offers them as tools of
#: `guidance` (docs/guidance.md "Guidance without a template"); collect writes only the record of
#: the session it names.
READ_ONLY_COMMANDS = {
    "collect": "Gives the guidance notes a template (--template) or a topic's tags (--tags a,b) get, "
               "general before specific, once per session (--session) and in pages. Use it before "
               "you work on or talk about a topic, and for a template's guidance before its input.",
    "check": "Finds what docs/guidance.md refuses in the project's guidance trees: front matter, "
             "names, tags, orphans, overrides, size and the generated files. Use it after changing "
             "a note.",
}


def make_parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="se_guidance.py", description=__doc__.splitlines()[0])
    commands = top.add_subparsers(dest="command", required=True)
    root = {"type": Path, "help": "the project (default: the folder holding se.toml at or above "
                                  "the working directory)"}
    collecting = commands.add_parser(
        "collect", help="print the guidance a template or a set of tags gets, general first",
        description="Print the notes a template gets, or those that carry every asked tag with "
                    "the notes at depth 0, by depth, tag count, modules first, then path.")
    asked = collecting.add_mutually_exclusive_group(required=True)
    asked.add_argument("--template", help="a template, as se_templates.py list names it")
    asked.add_argument("--tags", help="the tags, comma-separated: notes that carry all of them")
    collecting.add_argument("--json", action="store_true",
                            help="print the notes as JSON: name, path, depth and tags")
    collecting.add_argument("--session", help="the session whose record names the notes already "
                                              "printed to it, and gets this page's (default: none, "
                                              "every note printed, nothing kept)")
    collecting.add_argument("--page", type=int, default=1,
                            help="without --session: the page of a longer answer (default: 1)")
    collecting.add_argument("--root", **root)
    checking = commands.add_parser(
        "check", help="find what docs/guidance.md refuses in the guidance trees",
        description="Check every note of the trees: front matter, keys, names, tags, orphans, "
                    "overrides and size. It exits 1 on a finding.")
    checking.add_argument("--root", **root)
    projecting = commands.add_parser(
        "project", help="write each tool file the notes implement, its generated part from them",
        description="Write the part of each file the notes' ```implements <path> blocks give, "
                    "in the notes' order, under a header that says it is generated.")
    projecting.add_argument("--root", **root)
    pinning = commands.add_parser(
        "pin", help="write tests/guidance-pins.yaml, every template's resolution",
        description="Write the committed table of the notes each template gets, in order, which "
                    "tests/test_guidance.py compares every resolution with.")
    pinning.add_argument("--root", **root)
    pinning.set_defaults(run=run_pin)
    collecting.set_defaults(run=run_collect)
    checking.set_defaults(run=run_check)
    projecting.set_defaults(run=run_project)
    return top


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    words = [args.command]
    routed = sibling("se_components").routed(
        Path(__file__), words, list(sys.argv[1 + len(words):] if argv is None else argv[len(words):]),
        args.command in INTERACTIVE_COMMANDS)
    if routed is not None:
        return routed
    try:
        return args.run(args)
    except Usage as error:
        print(error)
        return 2


if __name__ == "__main__":
    sys.exit(main())
