# se:template se/python-module 1.0.0
"""Code templates (docs/templates.md "Code templates"): the part of scripts/templates.py's engine
that reads a code template's files and scaffolds them, which the engine loads only for a code
template or the command `templates.py scaffold`.

A code template (`kind: code`, templates.CODE) is an adapter without a checker of its own whose
`lines` hold the shape of the files it claims (`applies.paths` with `file.write`, selected by its
`marker_pattern`, the marker line it writes); the engine checks a claimed file by them as by any
adapter's. Its body is the files `scaffold` writes, each a `## <path>` heading followed by one
fenced block, the file's text, a fence of more backticks where the text holds three; between them
only blank lines (`code_data`, which templates.note_data calls, keeping the files under
templates.CODE_FILES for `Template.code`).

- The paths and texts take the placeholders `{{name}}` (the file's stem or the folder's name),
  `{{ident}}` (it with `_` for each run of other characters), `{{package}}` (it without them),
  `{{says}}`, `{{template}}` (`<repository>/<name>`) and `{{version}}` (CODE_PLACEHOLDERS); any
  other is refused at load, as are fields, an unclosed fence and a file named twice.
- `scaffold(template, path, says, name=)` gives the files, writing nothing: a template of one file
  the file `path`, one of several the files in the folder `path`.
- `templates.py scaffold <template> --path PATH --says LINE [--name NAME] [--root DIR]` (`run`)
  writes them, refusing a file that exists and one the template claiming it would refuse, and
  prints `wrote <path>: <template> <version>` per file.
- A code template has no fields to fill: `templates.fill` names its scaffold (`call`). Where every
  template that claims a file is a code template, a file none takes is refused naming the scaffold
  (templates.py's docstring: Selection, for a file).
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import templates

HERE = Path(__file__).resolve().parent
#: A code template's placeholders, `{{<name>}}`, in its paths and files (`scaffold`).
PLACEHOLDER = re.compile(r"\{\{([a-z]+)\}\}")
CODE_PLACEHOLDERS = ("name", "ident", "package", "says", "template", "version")
#: A scaffolded file's name: lower-case letters, digits, dashes and underscores, a letter first.
CODE_NAME = re.compile(r"[a-z][a-z0-9_-]*\Z")
SCAFFOLD = "templates.py scaffold"


def code_data(data: dict[str, object], body: str, where: str, first: int) -> dict[str, object]:
    """A code template note's data: no fields, and its body the files `scaffold` writes, each a
    `## <path>` heading followed by one fenced block, the file's text; outside them blank lines only."""
    if data.get("fields"):
        raise templates.TemplateError(f"{where}: a code template has no fields; its adapter's lines hold its shape")
    lines = body.splitlines(keepends=True)
    files: list[list[str]] = []
    index = 0
    while index < len(lines):
        number = first + index
        if not lines[index].strip():
            index += 1
            continue
        heading = re.match(r"^## +(\S.*?)[ \t]*$", lines[index].rstrip("\r\n"))
        if heading is None:
            raise templates.TemplateError(f"{where}:{number}: a code template's body holds only `## <path>` "
                                "headings, each followed by one fenced block, the file's text")
        path = heading.group(1).strip("`")
        index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1
        opening = templates.FENCE.match(lines[index]) if index < len(lines) else None
        if opening is None:
            raise templates.TemplateError(f"{where}:{number}: the file {path} has no fenced block under its heading")
        fence = opening.group(1)
        index += 1
        start = index
        while index < len(lines) and not (set(stripped := lines[index].strip()) == {fence[0]}
                                          and len(stripped) >= len(fence)):
            index += 1
        if index == len(lines):
            raise templates.TemplateError(f"{where}:{number}: the fenced block of {path} is never closed")
        files.append([path, "".join(lines[start:index])])
        index += 1
    if not files:
        raise templates.TemplateError(f"{where}: a code template's body holds the files it scaffolds, each a "
                            "`## <path>` heading followed by one fenced block")
    paths = [path for path, _ in files]
    if len(set(paths)) != len(paths):
        raise templates.TemplateError(f"{where}: a code template names each file once; it names "
                            f"{', '.join(sorted({path for path in paths if paths.count(path) > 1}))} twice")
    for path, text in files:
        for name in PLACEHOLDER.findall(path + text):
            if name not in CODE_PLACEHOLDERS:
                raise templates.TemplateError(f"{where}: {{{{{name}}}}} in {path} is no placeholder; the "
                                    f"placeholders are {', '.join(CODE_PLACEHOLDERS)}")
    data[templates.CODE_FILES] = files
    return data


def call(template: templates.Template, path: object) -> str:
    """The scaffold command that writes `path` from the code template `template`."""
    return f"uv run python {HERE / 'templates.py'} scaffold {template.name} --path {path} --says <one line>"


def code_values(template: templates.Template, name: str, says: str) -> dict[str, str]:
    """What each placeholder of `template` stands for, for the file or module `name` that `says`."""
    return {"name": name, "ident": re.sub(r"[^0-9a-z]+", "_", name.lower()).strip("_"),
            "package": re.sub(r"[^0-9a-z]", "", name.lower()), "says": says,
            "template": f"{template.repository}/{template.name}", "version": template.version}


def scaffold(template: templates.Template, path: Path, says: str, name: str | None = None) -> dict[Path, str]:
    """The files the code template `template` scaffolds at `path`, each its text with the
    placeholders filled (the module docstring: Code templates). A template of one file writes the
    file `path`, named by its stem; one of several writes them into the folder `path`, named by
    it; `name` names either otherwise. Writes nothing."""
    if template.kind != templates.CODE:
        raise templates.TemplateError(f"{SCAFFOLD}: {template.name} is a {template.kind} template; only a code "
                            "template scaffolds, a document is filled (templates.py fill)")
    single = len(template.code) == 1
    name = name or (path.stem if single else path.name)
    if not CODE_NAME.match(name):
        raise templates.TemplateError(f"{SCAFFOLD}: {name!r} is no name for a scaffolded file: lower-case "
                            "letters, digits, dashes and underscores, a letter first")
    says = " ".join(says.split())
    if not says or '"""' in says or "`" in says:
        raise templates.TemplateError(f"{SCAFFOLD}: --says is the one line the file opens with, what it does; "
                            'give it, without """ or backticks')
    values = code_values(template, name, says)

    def filled(text: str) -> str:
        return PLACEHOLDER.sub(lambda match: values[match.group(1)], text)

    if single:
        return {path: filled(template.code[0][1])}
    return {path / filled(relative): filled(text) for relative, text in template.code}


def run(catalog: dict[str, templates.Template], options: argparse.Namespace) -> int:
    """`scaffold`: write the files a code template makes at `--path`, each checked first against the
    template that claims it, or refuse, writing nothing."""
    template = templates._template(catalog, options.template)
    root = templates._root(options.path, options.root)
    made = scaffold(template, options.path, options.says, options.name)
    for path, text in made.items():
        if path.exists():
            raise templates.TemplateError(f"{SCAFFOLD}: {path} exists; a scaffold writes new files only, so "
                                "edit the one there")
        try:
            relative = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
        chosen = templates.select(catalog, templates.FILE_ACTION, text, path=relative)
        found = [*chosen.findings, *(templates.check(chosen.template, templates.parse(chosen.template, text))
                                     if chosen.template is not None else ())]
        refused = [item for item in found if item.severity == templates.REFUSE]
        if refused:
            raise templates.TemplateError("\n".join([f"{SCAFFOLD}: {template.name} scaffolds {relative}, which "
                                            "breaks the template that claims it; fix the template:",
                                            *templates._capped(refused)]))
    for path, text in made.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path}: {template.name} {template.version}")
    return 0
