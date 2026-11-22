#!/usr/bin/env python3
"""SE's switches and which of them are on: a read-only view over the table `scripts/switches/`.

The table is a folder of TOML files, one per group (`core.toml` first); a later module adds a
file of its own, so no two changes edit one table. Each `[[switch]]` row names a value that flips
behaviour, the file that reads it, its built-in default and the layers that reader consults, in
its order; `core.toml`'s header owns the keys of a row. Each `[[not_switch]]` names, with its
why, an `SE_*` variable that flips nothing, or se.toml keys that flip nothing, so the drift list
leaves them out. Keys are named in the table's own notation, which only the drift list reads:
`[table]` covers every key under that table, `[table] key` covers `table.key` and every key under
it; a cover matches whole dotted parts only, so `[outside]` covers `outside.SE` but not
`outside-text.envelope`. `parse` refuses any other not_switch name.

`in_effect` is a pure function: given the table and what each layer holds, it says for each
switch its state (on, off or set) and the layer that answered, `default` where none did. It reads
no file, environment or process; `main` is the thin wiring that reads them for it.

`se_switches.py [--json] [--root DIR] [--drift]` prints name, kind, state and the answering
layer, never a raw value, a token or a path; it writes nothing, starts nothing and exits 0.
`--drift` adds a report-only list: the `SE_*` names se's `scripts/`, `kern/` and `components/`
quote and the se.toml keys of the root that no file of the table names. Nothing calls it, and no
reader reads its switch through it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

SE_ROOT = Path(__file__).resolve().parents[1]
TABLE = Path(__file__).resolve().parent / "switches"
KINDS = ("environment", "se.toml", "wiring-instance", "wiring-wire", "local-file", "command-flag")
LAYERS = ("environment", "local", "se.toml", "wiring", "wiring-overlay", "public-check-local")
STATES = ("on", "off", "set")
ROW_KEYS = {"name", "kind", "reader", "default", "layers", "key", "on", "off", "other", "fold",
            "help", "note"}
REQUIRED = ("name", "kind", "reader", "default", "layers", "help")
TOML_LAYERS = ("local", "se.toml")
#: What the drift list reads under se's checkout, and the names it counts as read there: a name
#: in quotes, or a shell's or PowerShell's variable.
DRIFT_DIRS = ("scripts", "components")
DRIFT_SUFFIXES = (".py", ".go", ".sh", ".ps1")
QUOTED_NAME = re.compile(r"""["'`](SE_[A-Z][A-Z0-9_]*)["'`]|\$\{?(SE_[A-Z][A-Z0-9_]*)|"""
                         r"""\$env:(SE_[A-Z][A-Z0-9_]*)""")
DEFAULT = "default"
#: A not_switch name: an `SE_*` variable, or se.toml keys as `[table]` or `[table] key`.
NOT_SWITCH_VARIABLE = re.compile(r"SE_[A-Z][A-Z0-9_]*")
BARE = r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*"
NOT_SWITCH_KEYS = re.compile(rf"\[({BARE})\](?: ({BARE}))?")


class TableError(ValueError):
    """A table file that does not parse or a row that breaks the format."""


@dataclass(frozen=True)
class Switch:
    name: str
    kind: str
    reader: str
    default: str
    layers: tuple[str, ...]
    help: str
    source: str
    key: str = ""
    on: tuple = ()
    off: tuple = ()
    other: str = "set"
    fold: bool = False
    note: str = ""


@dataclass(frozen=True)
class Table:
    switches: tuple[Switch, ...]
    not_switches: tuple[str, ...] = ()

    def names(self) -> set[str]:
        return {switch.name for switch in self.switches} | set(self.not_switches)

    def covers(self) -> tuple[str, ...]:
        """The dotted se.toml keys the not_switch key names cover, each with every key under it."""
        found = []
        for name in self.not_switches:
            match = NOT_SWITCH_KEYS.fullmatch(name)
            if match:
                found.append(".".join(part for part in match.groups() if part))
        return tuple(found)


def covered(key: str, covers: Iterable[str]) -> bool:
    """Whether the dotted `key` is a cover or lies under one, by whole dotted parts."""
    return any(key == cover or key.startswith(cover + ".") for cover in covers)


@dataclass(frozen=True)
class Effect:
    """One switch in effect: `member` is the instance, wire or label of a switch that has many."""
    name: str
    kind: str
    state: str
    layer: str
    member: str = ""


def row(data: object, where: str) -> Switch:
    """A `[[switch]]` row, checked against the format (`core.toml`'s header)."""
    if not isinstance(data, dict):
        raise TableError(f"{where}: a switch is a table")
    unknown = sorted(set(data) - ROW_KEYS)
    missing = [key for key in REQUIRED if key not in data]
    if unknown or missing:
        raise TableError(f"{where}: unknown keys {unknown}, missing keys {missing}")
    name = data["name"]
    if not isinstance(name, str) or not name:
        raise TableError(f"{where}: name is no text")
    where = f"{where} ({name})"
    if data["kind"] not in KINDS:
        raise TableError(f"{where}: kind is one of {', '.join(KINDS)}")
    if data["default"] not in STATES or data.get("other", "set") not in STATES:
        raise TableError(f"{where}: default and other are one of {', '.join(STATES)}")
    layers = data["layers"]
    if not isinstance(layers, list) or not layers or any(layer not in LAYERS for layer in layers):
        raise TableError(f"{where}: layers is a list of {', '.join(LAYERS)}")
    if len(set(layers)) != len(layers):
        raise TableError(f"{where}: a layer appears twice")
    needs_key = data["kind"] in ("wiring-instance", "wiring-wire") or any(
        layer in TOML_LAYERS for layer in layers)
    if needs_key and not isinstance(data.get("key"), str):
        raise TableError(f"{where}: a switch read from a TOML layer names its key")
    for listed in ("on", "off"):
        if not isinstance(data.get(listed, []), list):
            raise TableError(f"{where}: {listed} is a list of values")
    for text in ("reader", "help", "note"):
        if not isinstance(data.get(text, ""), str):
            raise TableError(f"{where}: {text} is text")
    if not isinstance(data.get("fold", False), bool):
        raise TableError(f"{where}: fold is true or false")
    return Switch(name=name, kind=data["kind"], reader=data["reader"], default=data["default"],
                  layers=tuple(layers), help=data["help"], source=where.split(":")[0],
                  key=data.get("key", ""), on=tuple(data.get("on", [])),
                  off=tuple(data.get("off", [])), other=data.get("other", "set"),
                  fold=data.get("fold", False), note=data.get("note", ""))


def parse(texts: Mapping[str, str]) -> Table:
    """The table from each file's name and text, in name order; refuses a name used twice."""
    switches: list[Switch] = []
    not_switches: list[str] = []
    seen: dict[str, str] = {}
    for source in sorted(texts):
        try:
            data = tomllib.loads(texts[source])
        except tomllib.TOMLDecodeError as error:
            raise TableError(f"{source}: not TOML: {error}") from None
        unknown = sorted(set(data) - {"switch", "not_switch"})
        if unknown:
            raise TableError(f"{source}: unknown tables {unknown}: a file holds [[switch]] and [[not_switch]]")
        names: list[str] = []
        for number, item in enumerate(data.get("switch", []), 1):
            switch = row(item, f"{source}: switch {number}")
            switches.append(switch)
            names.append(switch.name)
        for number, item in enumerate(data.get("not_switch", []), 1):
            if not (isinstance(item, dict) and isinstance(item.get("name"), str)
                    and isinstance(item.get("why"), str) and set(item) == {"name", "why"}):
                raise TableError(f"{source}: not_switch {number} holds a name and why")
            if not (NOT_SWITCH_VARIABLE.fullmatch(item["name"])
                    or NOT_SWITCH_KEYS.fullmatch(item["name"])):
                raise TableError(f"{source}: not_switch {number} ({item['name']}): a name is an "
                                 "SE_* variable, `[table]` or `[table] key`")
            not_switches.append(item["name"])
            names.append(item["name"])
        for name in names:
            if name in seen:
                raise TableError(f"{source}: {name} is named in {seen[name]} already")
            seen[name] = source
    return Table(tuple(switches), tuple(not_switches))


def load(folder: Path = TABLE) -> Table:
    """The table of every TOML file in `folder`."""
    return parse({path.name: path.read_text(encoding="utf-8") for path in folder.glob("*.toml")})


def listed(values: tuple, value: object) -> bool:
    """Whether `value` is one of `values`, a bool never matching a number."""
    return any(type(item) is type(value) and item == value for item in values)


def state(switch: Switch, value: object) -> str:
    """The state the value of a switch reads as: its on and off lists, a bool, else its other."""
    if switch.fold and isinstance(value, str):
        value = value.lower()
    if listed(switch.off, value):
        return "off"
    if listed(switch.on, value):
        return "on"
    if isinstance(value, bool):
        return "on" if value else "off"
    return switch.other


def dotted(document: Mapping, key: str) -> tuple[bool, object]:
    """Whether the dotted `key` is in the TOML `document`, and its value."""
    here: object = document
    for part in key.split("."):
        if not isinstance(here, Mapping) or part not in here:
            return False, None
        here = here[part]
    return True, here


def members(switch: Switch, layers: Mapping[str, Mapping]) -> list[Effect]:
    """The effects of a wiring switch: one per instance or wire, in its layers' order."""
    table = "instances" if switch.kind == "wiring-instance" else "wires"
    found: list[Effect] = []
    for layer in switch.layers:
        entries = layers.get(layer, {}).get(table, {})
        for member in entries if isinstance(entries, Mapping) else ():
            entry = entries[member]
            if isinstance(entry, Mapping) and switch.key in entry:
                found.append(Effect(switch.name, switch.kind, state(switch, entry[switch.key]),
                                    layer, member))
            else:
                found.append(Effect(switch.name, switch.kind, switch.default, DEFAULT, member))
    return found


def in_effect(table: Table, environment: Mapping[str, str | None], local: Mapping,
              project: Mapping, wiring: Mapping, overlay: Mapping,
              public_local: Iterable[str]) -> list[Effect]:
    """Each switch's state and the layer that answered, following the row's own layer order.

    `environment` holds the names of the set variables, with the value of a listed switch only
    (None for the rest); `local`, `project`, `wiring` and `overlay` are the parsed
    `~/.se/local.toml`, `se.toml`, `wiring.toml` and `.se/wiring.toml`; `public_local` is the set of
    labels the local public-check list switches off. A switch nothing answers takes its default;
    one with members (instances, wires, labels) and none of them gives one default effect."""
    layers = {"local": local, "se.toml": project, "wiring": wiring, "wiring-overlay": overlay}
    labels = sorted(set(public_local))
    effects: list[Effect] = []
    for switch in table.switches:
        if switch.kind in ("wiring-instance", "wiring-wire"):
            found = members(switch, layers)
        elif switch.layers == ("public-check-local",):
            found = [Effect(switch.name, switch.kind, "on", "public-check-local", label)
                     for label in labels]
        else:
            found = []
            for layer in switch.layers:
                if layer == "environment":
                    present, value = switch.name in environment, environment.get(switch.name)
                else:
                    present, value = dotted(layers[layer], switch.key)
                if present:
                    found = [Effect(switch.name, switch.kind, state(switch, value), layer)]
                    break
        effects.extend(found or [Effect(switch.name, switch.kind, switch.default, DEFAULT)])
    return effects


def keys(document: Mapping, prefix: str = "") -> list[str]:
    """Every leaf key of a TOML document, dotted."""
    found: list[str] = []
    for key, value in document.items():
        name = f"{prefix}{key}"
        found.extend(keys(value, name + ".") if isinstance(value, Mapping) else [name])
    return found


def drift(table: Table, texts: Iterable[str], project: Mapping) -> dict[str, list[str]]:
    """The `SE_*` names the code texts quote and the se.toml keys that no file of the table names,
    a key a not_switch covers counting as named."""
    named = table.names()
    quoted = {next(group for group in match.groups() if group)
              for text in texts for match in QUOTED_NAME.finditer(text)}
    project_keys = {switch.key for switch in table.switches if "se.toml" in switch.layers}
    covers = table.covers()
    return {"environment": sorted(quoted - named),
            "se.toml": sorted(key for key in set(keys(project)) - project_keys
                              if not covered(key, covers))}


# The thin wiring: read each layer, never write.

def read_toml(path: Path, problems: list[str], label: str) -> dict:
    """The TOML at `path`, {} where it is missing or unreadable (named by `label`, never by path)."""
    try:
        return tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        problems.append(f"{label} is not readable TOML; read as empty")
        return {}


def read_public_local(root: Path, problems: list[str]) -> set[str]:
    """The labels the root's local public-check list switches off, by its owner's reader."""
    try:
        import public_check  # scripts/ is on the path: this script's own folder
        local = public_check.load_local(root)
    except Exception:  # its owner refused it; its message may quote the list, so none is shown
        problems.append("the local public-check list is not readable; read as empty")
        return set()
    return set(local.off) if local else set()


def code_texts(root: Path = SE_ROOT) -> list[str]:
    """The texts of se's code the drift list reads."""
    texts: list[str] = []
    for folder in DRIFT_DIRS:
        for path in sorted((root / folder).rglob("*")):
            if (path.suffix in DRIFT_SUFFIXES and path.is_file() and "__pycache__" not in path.parts
                    and not path.name.endswith("_test.go")):
                try:
                    texts.append(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError):
                    continue
    return texts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print SE's switches, whether each is on and "
                                     "which layer answered; read-only, always exits 0.")
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument("--root", type=Path, default=Path.cwd(),
                        help="the repository whose layers are read; default: the working directory")
    parser.add_argument("--drift", action="store_true",
                        help="also list SE_* names and se.toml keys no file of the table names")
    args = parser.parse_args(argv)
    problems: list[str] = []
    try:
        table = load()
    except (OSError, TableError) as error:
        print(f"se_switches: the table does not parse: {error}", file=sys.stderr)
        return 0
    listed_names = {switch.name for switch in table.switches if "environment" in switch.layers}
    environment = {name: (os.environ[name] if name in listed_names else None) for name in os.environ}
    root = args.root
    project = read_toml(root / "se.toml", problems, "se.toml")
    effects = in_effect(
        table, environment,
        local=read_toml(Path.home() / ".se" / "local.toml", problems, "the machine's local.toml"),
        project=project, wiring=read_toml(root / "wiring.toml", problems, "wiring.toml"),
        overlay=read_toml(root / ".se" / "wiring.toml", problems, "the ad hoc wiring"),
        public_local=read_public_local(root, problems))
    drifted = drift(table, code_texts(), project) if args.drift else None
    if args.json:
        out: dict[str, object] = {"switches": [asdict(effect) for effect in effects],
                                  "problems": problems}
        if drifted is not None:
            out["drift"] = drifted
        print(json.dumps(out, indent=2))
        return 0
    rows = [(effect.name + (f" {effect.member}" if effect.member else ""), effect.kind,
             effect.state, effect.layer) for effect in effects]
    width = [max((len(row_[column]) for row_ in rows), default=0) for column in range(3)]
    for row_ in rows:
        print("  ".join(cell.ljust(width[column]) for column, cell in enumerate(row_[:3]))
              + "  " + row_[3])
    for problem in problems:
        print(f"note: {problem}")
    if drifted is not None:
        print("\nDrift (report only): named by no file of the table")
        for kind, names in drifted.items():
            print(f"  {kind}: {', '.join(names) if names else 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
