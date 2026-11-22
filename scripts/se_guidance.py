#!/usr/bin/env python3
"""Guidance: SE reads the guidance trees of a project and of its modules, resolves them for a
template or a set of tags, and checks them, as docs/guidance.md designs ("Notes in folders",
"Resolution", "Guidance without a template"). It is the command component `guidance`.

**Trees.** A guidance tree is the folder `guidance/` at the root of a source: each module the
project's se.toml declares, in its order, at its folder on this machine (se_modules.py
`module_dirs`), then the project itself. A module without the folder, or not placed, has none.

**Notes.** Every `*.md` file of a tree is one note. Its front matter, between `---` lines, holds
one `key: value` a line, the value plain, quoted (`'...'` or `"..."`) or a list (`[a, b]`):

- `name` and `description`, the two keys a skill needs, both required;
- `tags`, a list, optional: tags beside those its folders give;
- `overrides`, optional: the name of the note it replaces (Resolution, below).

No other key loads. A note's depth is the number of folders between it and `guidance/`; its tags
are every folder name on that way and its own `tags`, as one set. A tag and a name are lowercase
words of letters and digits joined by single dashes (TAG).

**Templates.** Until templates exist, SE's forms are the templates (docs/guidance.md): each
`forms/<name>.toml` of a source, but `forms/terms.toml`, is the template `<name>` with the tags of
its `tags` list (none where it sets none); a project's form replaces a module's of the same name.

**Resolution.** A template gets every note whose tags it carries all of. A tag query
(`--tags a,b`) gets every note that carries all the asked tags, and every note at depth 0. Where a
note of the resolution names another in `overrides`, the named note is dropped from it; the
overriding note prints at its own place. The notes print by depth, lowest first; at equal depth by
the number of tags, fewest first; then the modules' notes before the project's, in se.toml's
order; then by path.

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
- a form whose `tags` is no list of tags.

**Commands.** `collect` and `check` only read; neither writes, calls GitHub or starts a model.

- `se_guidance.py collect (--template NAME | --tags A,B) [--json] [--root ROOT]` prints the
  resolution: a line naming what was resolved and how many notes, then each note as a `##` heading
  of its name, a line with its file, depth and tags, and its text. `--json` prints the list of
  notes instead (`name`, `path`, `depth`, `tags`). An unknown template is answered with the list of
  templates, exit code 2; a tag no note carries is named, with the tags that exist, before the
  rest. A note that does not load is left out and named on stderr.
- `se_guidance.py check [--root ROOT]` prints every finding, one a line, exit code 1, or `passes:
  <n> notes, <m> templates`, exit code 0.

`--root` is the project (default: the folder holding se.toml at or above the working directory,
else the working directory). Exit code 2 is a usage or setup error, named.
"""

from __future__ import annotations

import argparse
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
FORMS = "forms"
TERMS_FILE = "terms.toml"
#: A tag, a folder name and a note's name: lowercase words of letters and digits joined by dashes.
TAG = re.compile(r"\A[a-z0-9]+(?:-[a-z0-9]+)*\Z")
#: The keys of a note's front matter: a skill's two, then the two of guidance, never a third.
SKILL_KEYS = ("name", "description")
KEYS = (*SKILL_KEYS, "tags", "overrides")
#: Where kern declares its page limit, in the kern clone se pins, and how.
PAGE_FILE = Path("mcp") / "page.go"
PAGE_LIMIT = re.compile(r"^const PageLimit = (\d+)$", re.MULTILINE)
CHECK = "se_guidance.py check"


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
    if not loads:
        return None
    return Note(name, scalar(keys["description"]), frozenset((*folders, *own)), folders,
                tuple(own), scalar(keys.get("overrides", "")), relative, source, len(data), body)


def read_templates(source: Source, templates: dict[str, Template], findings: list[str]) -> None:
    folder = source.root / FORMS
    if not folder.is_dir():
        return
    for path in sorted(folder.glob("*.toml")):
        if path.name == TERMS_FILE:
            continue
        where = source.where(path.relative_to(source.root).as_posix())
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            findings.append(f"{where}: not TOML ({error}); fix the form")
            continue
        tags = data.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(t, str) and TAG.match(t) for t in tags):
            findings.append(f"{where}: tags is no list of tags, lowercase words joined by "
                            "dashes; fix the form's tags")
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
    return Loaded(sorted(notes, key=Note.order), templates, findings)


# Resolution.

def resolved(chosen: list[Note]) -> list[Note]:
    """`chosen` without the notes an override among them names, in the documented order."""
    dropped = {note.overrides for note in chosen if note.overrides}
    return sorted((note for note in chosen if note.name not in dropped), key=Note.order)


def for_template(notes: list[Note], template: Template) -> list[Note]:
    return resolved([note for note in notes if note.tags <= template.tags])


def for_tags(notes: list[Note], tags: frozenset[str]) -> list[Note]:
    return resolved([note for note in notes if tags <= note.tags or note.depth == 0])


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
    return findings


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


def printed(notes: list[Note], heading: str, as_json: bool) -> str:
    if as_json:
        return json.dumps([{"name": note.name, "path": note.where, "depth": note.depth,
                            "tags": sorted(note.tags)} for note in notes], indent=2) + "\n"
    parts = [f"{heading}: {plural(len(notes), 'note')}, general before specific.\n"]
    for note in notes:
        tags = ", ".join(sorted(note.tags)) or "none"
        parts.append(f"\n## {note.name}\n\n`{note.where}` · depth {note.depth} · tags: {tags}\n\n"
                     f"{note.body.rstrip()}\n")
    return "".join(parts)


def run_collect(options: argparse.Namespace) -> int:
    loaded = load(project_root(options.root))
    for finding in loaded.findings:
        print(f"left out: {finding} ({CHECK})", file=sys.stderr)
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
        if unknown and not options.json:
            print(f"No note carries the tag{'' if len(unknown) == 1 else 's'} "
                  f"{', '.join(unknown)}; the tags are: {', '.join(sorted(carried)) or 'none'}.\n")
    print(printed(notes, heading, options.json), end="")
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


#: se_guidance.py's commands as one kern component (README "Commands as components"); each
#: command's usage and help come from make_parser.
COMPONENTS = (sibling("se_components").Group(
    "guidance", "Guidance",
    "SE's guidance: collect resolves the guidance trees of the project and its modules for a "
    "template or a set of tags, general before specific, and check finds what docs/guidance.md "
    "refuses in them.",
    ("collect", "check")),)
#: The commands that go through kern where it runs (se_components.routed): both only read.
INTERACTIVE_COMMANDS = frozenset({"collect", "check"})


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
    asked.add_argument("--template", help="a template, a form's name")
    asked.add_argument("--tags", help="the tags, comma-separated: notes that carry all of them")
    collecting.add_argument("--json", action="store_true",
                            help="print the notes as JSON: name, path, depth and tags")
    collecting.add_argument("--root", **root)
    checking = commands.add_parser(
        "check", help="find what docs/guidance.md refuses in the guidance trees",
        description="Check every note of the trees: front matter, keys, names, tags, orphans, "
                    "overrides and size. It exits 1 on a finding.")
    checking.add_argument("--root", **root)
    collecting.set_defaults(run=run_collect)
    checking.set_defaults(run=run_check)
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
