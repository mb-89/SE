# se:template se/python-module 1.0.0
"""Interfaces: the texts SE's sessions pass to each other, written and read through the schema
generated from their interface templates (docs/templates.md "Nesting" and "The schema").

**The generated files.** Every interface template with fields (`kind: interface` in
`templates/<name>.md`, scripts/templates.py's docstring) has one generated file beside the code that
uses it, `scripts/interfaces/<name>.json` (GENERATED), which `templates.py interfaces` writes and
nothing writes by hand. It holds `template` (`se/<name>`), `version`, `says`, `message` where the
template has one, and `schema`, the JSON Schema `templates.py schema <name>` prints. A test
(`tests/test_interfaces.py`) and `templates.py interfaces --check` fail where a file differs from
its template; `templates.py interfaces` writes it again.

**A message.** A message interface declares `message`, the one line it is, its fields as
`{<field>}`, each field once and every field of the template in it (`placeholders`). `line` writes
the line from the fields, `fields_of` reads the fields back from a line that is one; a field's
value is one line, and the text between two fields stands as it is written. scripts/templates.py
reads and writes a message template's document through these two, so the engine and the code
follow one format.

**A snippet.** A message of several lines is a snippet, a short fixed text such as SE's start
report (`templates/boot-report.md`). Beside `line` fields it may hold two kinds, which the generated
file carries as `rows` and `cases` so its writer needs no engine:

- a `rows` field stands alone on its message line, `{<field>}`, and is written as one line per row,
  each its `row` line with the row's columns as `{<column>}` (none where there is no row); its value
  is a list of mappings, column to text;
- a `case` field is one of its `cases`, a mapping of a key to one line, which may name the
  snippet's line fields that stand in no other line as `{<field>}`; its value is the key.

`text` writes a snippet from the fields, `snippet_fields` reads them back from a text that is
one, line by line; `line` and `fields_of` are its one-line case.

**Use.** `write(name, values)` checks the values against the generated schema (`problems`: a
required field missing or empty, a field the schema does not name, a value of another type, a
choice outside its `enum`) and gives the line, or raises InterfaceError naming each problem and
the template. `read(name, text)` gives the fields of the first line of `text` that is the message,
else None. Both read only the generated file, never the template: the code that sends and reads a
message needs no engine.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: The folder of the generated files, beside the scripts that use them.
GENERATED = ROOT / "scripts" / "interfaces"
SUFFIX = ".json"
PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


class InterfaceError(Exception):
    """A message its schema refuses, or a generated file that is missing or unreadable: the text
    names the template and the remedy."""


def placeholders(message: str) -> list[str]:
    """The fields a message line names, in their order."""
    return PLACEHOLDER.findall(message)


def _pattern(message: str) -> re.Pattern:
    """A whole line that is `message`: each field one line of at least one character, the text
    between them as it stands."""
    parts, index = [], 0
    for match in PLACEHOLDER.finditer(message):
        parts.append(re.escape(message[index:match.start()]))
        parts.append(f"(?P<{match.group(1)}>.+?)")
        index = match.end()
    parts.append(re.escape(message[index:]))
    return re.compile("".join(parts))


def line(message: str, values: dict[str, object]) -> str:
    """`message` with each field's value; a value is one line, its whitespace runs made one space."""
    return PLACEHOLDER.sub(lambda match: " ".join(str(values.get(match.group(1), "")).split()),
                           message)


def text(message: str, values: dict[str, object], rows: dict[str, str] | None = None,
         cases: dict[str, dict[str, str]] | None = None) -> str:
    """A snippet with each field's value: a `rows` field's line one line per row, a `case` field
    its case's line filled in turn, every other field as `line` writes it."""
    rows, cases = rows or {}, cases or {}
    out = []
    for template_line in message.split("\n"):
        alone = PLACEHOLDER.fullmatch(template_line.strip())
        if alone and alone.group(1) in rows:
            out += [line(rows[alone.group(1)], row) for row in values.get(alone.group(1)) or []
                    if isinstance(row, dict)]
            continue
        for name, chosen in cases.items():
            if "{" + name + "}" in template_line:
                template_line = template_line.replace("{" + name + "}", chosen.get(str(values.get(name)), ""))
        out.append(line(template_line, values))
    return "\n".join(out)


def snippet_problem(message: str, fields: list[tuple[str, str, dict[str, str]]]) -> str:
    """What is wrong with a snippet of `fields`, each (name, kind, cases), or "": each field named
    once, in its lines or a case's; a rows field alone on its line; a field a case names a line;
    every field a line, a choice, rows or a case."""
    in_cases = {name for _, _, cases in fields for text in cases.values() for name in placeholders(text)}
    named = placeholders(message) + sorted(in_cases)
    names = [name for name, _, _ in fields]
    if sorted(named) != sorted(names):
        return (f"message names {', '.join(named) or 'no field'}; it names each field once, in its "
                f"lines or a case's: {', '.join(names)}")
    lines = [line.strip() for line in message.split("\n")]
    for name, kind, _ in fields:
        if kind not in ("line", "choice", "rows", "case"):
            return f"field {name} of a snippet is a line, a choice, rows or a case"
        if kind == "rows" and "{" + name + "}" not in lines:
            return f"rows field {name} stands alone on its line, {{{name}}}"
        if name in in_cases and kind != "line":
            return f"field {name} named in a case is a line"
    return ""


def snippet_fields(message: str, written: str, rows: dict[str, str] | None = None,
                   cases: dict[str, dict[str, str]] | None = None) -> dict[str, object] | None:
    """The fields of `written` where it is the snippet `message`, line by line, trailing blank
    lines aside; else None. A `rows` field takes every following line its row line matches."""
    rows, cases = rows or {}, cases or {}
    lines = written.rstrip("\n").split("\n")
    found: dict[str, object] = {}
    at = 0
    for template_line in message.split("\n"):
        alone = PLACEHOLDER.fullmatch(template_line.strip())
        if alone and alone.group(1) in rows:
            taken = []
            while at < len(lines) and (row := fields_of(rows[alone.group(1)], lines[at])) is not None:
                taken.append(row)
                at += 1
            found[alone.group(1)] = taken
            continue
        if at >= len(lines):
            return None
        options = [(None, template_line)]
        for name, chosen in cases.items():
            if "{" + name + "}" in template_line:
                options = [(key, template_line.replace("{" + name + "}", case)) for key, case in chosen.items()]
                break
        for key, option in options:
            if not PLACEHOLDER.search(option):
                matched = {} if option.strip() == lines[at].strip() else None
            else:
                matched = fields_of(option, lines[at])
            if matched is not None:
                found.update(matched)
                if key is not None:
                    found[next(name for name in cases if "{" + name + "}" in template_line)] = key
                break
        else:
            return None
        at += 1
    return found if all(not rest.strip() for rest in lines[at:]) else None


def fields_of(message: str, text: str) -> dict[str, str] | None:
    """The fields of `text` where it is one `message` line, stripped; else None."""
    match = _pattern(message).fullmatch(text.strip())
    return None if match is None else {key: value.strip() for key, value in match.groupdict().items()}


def generated(name: str, folder: Path = GENERATED) -> dict[str, object]:
    """The generated file of interface template `name`."""
    path = folder / f"{name}{SUFFIX}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InterfaceError(f"interfaces: no generated schema for {name} at {path} ({error}); run "
                             "`uv run python scripts/templates.py interfaces`") from error
    if not isinstance(data, dict) or not isinstance(data.get("schema"), dict):
        raise InterfaceError(f"interfaces: {path} holds no schema; run "
                             "`uv run python scripts/templates.py interfaces`")
    return data


def _type_problem(key: str, shape: dict, value: object) -> str:
    """What is wrong with one value against its property, or ""."""
    kind = shape.get("type")
    if kind == "string":
        if not isinstance(value, str):
            return f"{key} is {type(value).__name__}; the schema takes a string"
        if "enum" in shape and value not in shape["enum"]:
            return f"{key} is {value!r}; one of {', '.join(map(str, shape['enum']))}"
    elif kind == "array":
        if not isinstance(value, list):
            return f"{key} is {type(value).__name__}; the schema takes a list"
        item = shape.get("items", {})
        return next((problem for number, entry in enumerate(value, 1)
                     if (problem := _type_problem(f"{key} item {number}", item, entry))), "")
    elif kind == "object":
        if not isinstance(value, dict):
            return f"{key} is {type(value).__name__}; the schema takes a mapping"
        inner = problems(shape, value) if "properties" in shape else []
        return f"{key}: {'; '.join(inner)}" if inner else ""
    elif kind == "boolean" and not isinstance(value, bool):
        return f"{key} is {type(value).__name__}; the schema takes true or false"
    return ""


def problems(schema: dict, values: dict[str, object]) -> list[str]:
    """What the generated `schema` (an object of named properties) refuses in `values`."""
    properties = schema.get("properties", {})
    found = [f"{key} is required" for key in schema.get("required", [])
             if values.get(key) in (None, "", [])]
    if schema.get("additionalProperties") is False:
        found += [f"{key} is no field of the schema; its fields are {', '.join(properties)}"
                  for key in values if key not in properties]
    found += [problem for key, value in values.items() if key in properties
              and value not in (None, "", []) and (problem := _type_problem(key, properties[key], value))]
    return found


def write(name: str, values: dict[str, object], folder: Path = GENERATED) -> str:
    """The message line of interface `name` with `values`, checked against its generated schema."""
    data = generated(name, folder)
    message = str(data.get("message") or "")
    if not message:
        raise InterfaceError(f"interfaces: {name} is no message; its template declares no message line")
    found = problems(data["schema"], values)
    if found:
        raise InterfaceError(f"interfaces: the {name} message ({data.get('template')} "
                             f"{data.get('version')}) refuses: {'; '.join(found)}")
    if "\n" in message:
        return text(message, values, data.get("rows"), data.get("cases"))
    return line(message, values)


def read(name: str, text: str, folder: Path = GENERATED) -> dict[str, object] | None:
    """The fields of the first line of `text` that is interface `name`'s message, else None; of a
    snippet, the fields of `text` where all of it is the snippet."""
    data = generated(name, folder)
    message = str(data.get("message") or "")
    if not message:
        raise InterfaceError(f"interfaces: {name} is no message; its template declares no message line")
    if "\n" in message:
        return snippet_fields(message, text, data.get("rows"), data.get("cases"))
    return next((found for candidate in text.splitlines()
                 if (found := fields_of(message, candidate)) is not None), None)
