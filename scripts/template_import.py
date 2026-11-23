#!/usr/bin/env python3
"""Import adapters: bring a template from its source tool into a template repository's Markdown
(docs/templates.md "Template repositories").

**Declaration.** A `templates/` folder, a template repository's or a project's own, lists the
templates it imports in `templates/imports.yaml`, YAML in the subset `templates.front_data` reads:

```yaml
imports:
  - name: meeting            # the template note the adapter writes, templates/meeting.md
    adapter: markdown        # one of ADAPTERS
    source: vault/Meeting.md # the source tool's template, relative to the folder above templates/
    version: 1.0.0           # the template's version, which the person moves
    kind: document           # and the template's other keys the source tool does not hold:
    reader: owner            # reader, says, tags and applies, as scripts/templates.py's
    says: "A meeting note."  # docstring (Template files) defines them
    tags: ["meeting"]
    applies: {"actions": ["file.write"], "paths": ["notes/*.md"]}
```

`name`, `adapter`, `source`, `version`, `kind` and `reader` are required (DECLARED). `source` is
relative and stays inside the repository's folder above `templates/`, so a pin carries it.

**Interface.** An adapter (`Adapter`) is asked in this order, and `refresh` asks it so, before every
fill (`templates.py fill`, `templates.refresh`):

1. `changed(entry, note)`: whether the template changed in its source tool since the note was
   written, `note` the text of `templates/<name>.md` now, None where there is none. The base
   compares the digest the note records, `imported: sha256:<hex>` of the declaration's entry and
   the source's text (`digest`), with the digest of both now.
2. Where it did, `note(entry)`: the template note, Markdown, which `refresh` writes to
   `templates/<name>.md`; the note is never edited by hand, as the next import overwrites it.
3. Only then the overlay, `templates/<name>.overlay.md`, applies, as scripts/templates.py loads the
   templates (its docstring: Overlays), and the fill fills from the result.

`refresh` reads every entry first and writes nothing where one fails: a declaration, a source or a
note that is wrong raises `templates.TemplateError` naming the file, the entry and the remedy.

**The Markdown adapter** (`markdown`, `MarkdownAdapter`) reads a Markdown template note, as an
Obsidian template is one: its front matter and the text above its first `##` heading (a page
title among it) are left out; each `##` heading is a section, a field of kind `text` named by its
heading (`field_name`); the comments in a section, `<!-- ... -->` and Obsidian's `%% ... %%`, are
the section's instruction, joined in turn; all else in a section (deeper headings, placeholders,
example text) is left out, and a heading inside a fenced block is none. A section without a comment
gets an empty instruction, which its overlay supplies. Two sections with the same field name, or
a source without a `##` heading, refuse. It writes no `interface`: its document is data.

**Command.** `template_import.py refresh [--templates DIR]` refreshes the imports of that folder
(default: `templates/` of the working directory) and names each template it wrote, `imported
<name> from <source> (<adapter>)`; exit 0, 2 on an error, which it names.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path, PurePosixPath

IMPORTS_FILE = "imports.yaml"
#: The keys of an import's entry: the required ones, then the template's keys it may add.
DECLARED = ("name", "adapter", "source", "version", "kind", "reader")
OPTIONAL = ("says", "tags", "applies")
#: The front matter key of an imported note: the digest it was written from.
IMPORTED = "imported"
NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
FIELD_NAME = re.compile(r"[^a-z0-9]+")
HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
COMMENTS = re.compile(r"<!--(.*?)-->|%%(.*?)%%", re.DOTALL)
SECTION_LEVEL = 2


def _sibling(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _error(message: str) -> Exception:
    return _sibling("templates").TemplateError(message)


@dataclass(frozen=True)
class Import:
    """One entry of `templates/imports.yaml`: the template, its adapter, its source and the
    template's keys the source does not hold (`header`), in the folder `templates`."""
    name: str
    adapter: str
    source: str
    header: dict = dataclass_field(compare=False)
    templates: Path = dataclass_field(compare=False)
    where: str = ""

    @property
    def source_path(self) -> Path:
        return self.templates.parent / self.source

    @property
    def note_path(self) -> Path:
        return self.templates / f"{self.name}{_sibling('templates').TEMPLATE_SUFFIX}"


def imports(folder: Path) -> list[Import]:
    """The imports `folder/imports.yaml` declares, in its order; none where there is no such file."""
    path = folder / IMPORTS_FILE
    if not path.is_file():
        return []
    where = f"{folder.name}/{IMPORTS_FILE}"
    data = _sibling("templates").front_data(path.read_text(encoding="utf-8"), where, first=1)
    if set(data) != {"imports"} or not isinstance(data["imports"], list):
        raise _error(f"{where}: holds one key, imports, a list of the templates the folder imports "
                     "(scripts/template_import.py's docstring)")
    found: list[Import] = []
    for number, entry in enumerate(data["imports"], 1):
        at = f"{where}: import {number}"
        if not isinstance(entry, dict):
            raise _error(f"{at} is no mapping; give its {', '.join(DECLARED)}")
        missing = [key for key in DECLARED if not entry.get(key)]
        unknown = sorted(set(entry) - set(DECLARED) - set(OPTIONAL))
        if missing or unknown:
            raise _error(f"{at}: " + "; ".join(
                [*([f"give {', '.join(missing)}"] if missing else []),
                 *([f"{', '.join(unknown)} is no key of an import; its keys are "
                    f"{', '.join((*DECLARED, *OPTIONAL))}"] if unknown else [])]))
        name, adapter, source = (str(entry[key]) for key in ("name", "adapter", "source"))
        if not NAME.match(name):
            raise _error(f"{at}: name {name!r} is the template's file name: lowercase words joined "
                         "by dashes")
        if adapter not in ADAPTERS:
            raise _error(f"{at}: adapter {adapter!r} is none of {', '.join(sorted(ADAPTERS))}")
        relative = PurePosixPath(source.replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts or re.match(r"^[A-Za-z]:", source):
            raise _error(f"{at}: source {source} is relative to the folder above templates/ and stays "
                         "inside it, so the repository's pin carries it")
        if name in {item.name for item in found}:
            raise _error(f"{at}: imports {name} a second time; import each template once")
        header = {key: entry[key] for key in (*DECLARED[3:], *OPTIONAL) if key in entry}
        found.append(Import(name, adapter, relative.as_posix(), header, folder, at))
    return found


class Adapter:
    """What every import adapter answers (the module docstring: Interface). A source tool's
    adapter reads its source (`read`) and writes the note (`note`); the base gives `digest` and
    `changed`, which the note's `imported` record answers."""

    name = ""

    def read(self, entry: Import) -> str:
        """The source's text, as the digest covers it."""
        try:
            return entry.source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise _error(f"{entry.where}: source {entry.source} cannot be read ({error}); give the "
                         "path of the source tool's template, relative to the folder above "
                         "templates/") from error

    def digest(self, entry: Import) -> str:
        """`sha256:<hex>` of the declaration's entry and the source's text."""
        declared = json.dumps({"name": entry.name, "adapter": entry.adapter, "source": entry.source,
                               **entry.header}, sort_keys=True)
        return "sha256:" + hashlib.sha256(declared.encode("utf-8") + b"\0"
                                          + self.read(entry).encode("utf-8")).hexdigest()

    def changed(self, entry: Import, note: str | None) -> bool:
        """Whether the source changed since `note` was written from it: no note, or one that records
        another digest."""
        return note is None or recorded(note) != self.digest(entry)

    def note(self, entry: Import) -> str:
        raise NotImplementedError


def recorded(note: str) -> str:
    """The digest an imported note records in its front matter, "" for none."""
    match = re.search(rf"^{IMPORTED}:[ \t]*\"?(sha256:[0-9a-f]+)\"?[ \t]*$",
                      note.split("\n---", 1)[0], re.MULTILINE)
    return match.group(1) if match else ""


def field_name(heading: str) -> str:
    """A section's field name: its heading in lowercase words joined by `_`, opening with a letter."""
    name = FIELD_NAME.sub("_", heading.lower()).strip("_")
    return f"section_{name}" if name[:1].isdigit() else name


def sections(text: str, where: str) -> list[tuple[str, str, str]]:
    """The `##` sections of a Markdown template note as (field, heading, instruction)."""
    text = text.replace("\r\n", "\n")
    if text.startswith("---\n"):
        end = text.find("\n---", 3)
        text = text[text.find("\n", end + 1) + 1:] if end >= 0 else text
    found: list[tuple[str, str, list[str], int]] = []
    fence = ""
    for number, line in enumerate(text.split("\n"), 1):
        opened = FENCE.match(line)
        if opened and (not fence or opened.group(1)[0] == fence[0] and len(opened.group(1)) >= len(fence)):
            fence = "" if fence else opened.group(1)
        heading = None if fence or opened else HEADING.match(line)
        if heading and len(heading.group(1)) == SECTION_LEVEL:
            found.append((field_name(heading.group(2)), heading.group(2), [], number))
        elif found and not (heading and len(heading.group(1)) < SECTION_LEVEL):
            found[-1][2].append(line)  # a page title is left out
    if not found:
        raise _error(f"{where}: no `##` heading; a Markdown template note's sections are its `##` "
                     "headings")
    made, seen = [], {}
    for name, heading, lines, number in found:
        if not name:
            raise _error(f"{where}:{number}: heading {heading!r} names no field; give it words")
        if name in seen:
            raise _error(f"{where}:{number}: heading {heading!r} is field {name} again, as line "
                         f"{seen[name]}; give each section its own heading")
        seen[name] = number
        said = [" ".join((match.group(1) or match.group(2) or "").split())
                for match in COMMENTS.finditer("\n".join(lines))]
        made.append((name, heading, " ".join(item for item in said if item).replace("-->", "->")))
    return made


def _value(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


class MarkdownAdapter(Adapter):
    """A Markdown template note's sections and comment instructions (the module docstring)."""

    name = "markdown"

    def note(self, entry: Import) -> str:
        if entry.header.get("kind") == _sibling("templates").INTERFACE:
            raise _error(f"{entry.where}: kind interface has no sections; a Markdown template note "
                         "imports as a document, a block or an entry")
        found = sections(self.read(entry), f"{entry.where}: source {entry.source}")
        lines = ["---",
                 f"# Imported from {entry.source} by scripts/template_import.py ({self.name}); never",
                 f"# edit it by hand: the next import overwrites it. {entry.name}.overlay.md adds to it.",
                 f"name: {entry.name}"]
        header = {"tags": [], **entry.header}
        lines += [f"{key}: {_value(header[key])}" for key in (*DECLARED[3:], *OPTIONAL) if key in header]
        lines += [f"{IMPORTED}: {_value(self.digest(entry))}", "fields:"]
        for name, _, _ in found:
            lines += [f"  - name: {_value(name)}", "    kind: text"]
        lines.append("---")
        for name, heading, says in found:
            lines += ["", f"## {heading}", "", f"<!-- {name}: {says} -->" if says else f"<!-- {name}: -->"]
        return "\n".join(lines) + "\n"


ADAPTERS: dict[str, Adapter] = {adapter.name: adapter for adapter in (MarkdownAdapter(),)}


def refresh(folder: Path) -> list[str]:
    """Bring each template `folder/imports.yaml` imports up to date: where its adapter says the
    source changed, write the note it answers. Every entry is read first, so an error writes
    nothing. Names each template written, `imported <name> from <source> (<adapter>)`."""
    written = []
    for entry in imports(folder):
        adapter = ADAPTERS[entry.adapter]
        path = entry.note_path
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if adapter.changed(entry, current):
            written.append((entry, adapter.note(entry)))
    for entry, text in written:
        entry.note_path.write_text(text, encoding="utf-8")
    return [f"imported {entry.name} from {entry.source} ({entry.adapter})" for entry, _ in written]


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="template_import.py",
                                     description="bring imported templates up to date from their source tools")
    commands = parser.add_subparsers(dest="command", required=True)
    refreshing = commands.add_parser("refresh", help="write each imported template whose source changed")
    refreshing.add_argument("--templates", type=Path, default=Path("templates"),
                            help="the templates/ folder whose imports.yaml lists them (default: ./templates)")
    options = parser.parse_args(arguments)
    try:
        lines = refresh(options.templates)
    except _sibling("templates").TemplateError as error:
        print(error, file=sys.stderr)
        return 2
    if lines:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
