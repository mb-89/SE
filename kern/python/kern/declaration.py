"""A component's declaration, its ``component.toml``, read as the Go core reads it.

The checks are the Go core's (``index.ParseDeclaration``): an unknown key, a
missing help, built-in value or command field, a type that is none, and another
contract version are refused. ``contract/declarations.json`` holds both readers
to the same refusals, and the declaration hash is the same: the SHA-256 of the
file's bytes, line ends read as LF.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The component contract's version this SDK speaks; the core refuses another.
CONTRACT = 1
#: A component's declaration file, beside its code.
FILE = "component.toml"
#: The prefix of the local port a run reads a config key by, as the core sends it.
CONFIG_PREFIX = "config/"

_PORT = re.compile(r"^[A-Za-z0-9-]+$")
_SHAPE = re.compile(r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+$")
_PLAIN = ("int", "float", "string", "bool")


class DeclarationError(ValueError):
    """A declaration the core would refuse."""


def digest(data: bytes) -> str:
    """The declaration hash a process attaches with: ``sha256:<hex>`` of its bytes, CRLF read as LF."""
    return "sha256:" + hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def type_ok(t: object) -> bool:
    """Whether t is a type: int, float, string, bool, [T], or a named shape such as github.issues."""
    if not isinstance(t, str):
        return False
    if t in _PLAIN or _SHAPE.match(t):
        return True
    return t.startswith("[") and t.endswith("]") and type_ok(t[1:-1])


def fits(value: Any, t: str) -> bool:
    """Whether a JSON value can stand in a port of type t, as Go's decoding takes it."""
    if t == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "string":
        return isinstance(value, str)
    if t == "bool":
        return isinstance(value, bool)
    if t.startswith("["):
        return value is None or (isinstance(value, list) and all(fits(v, t[1:-1]) for v in value))
    return True  # a named shape is any JSON value


def kind(value: Any) -> str:
    """How a refusal names a value's kind: its Python type."""
    return "null" if value is None else type(value).__name__


@dataclass
class Port:
    """One declared port: its type, built-in value and help."""

    name: str
    type: str
    builtin: Any = None
    help: str = ""
    derived: bool = False
    family: bool = False


@dataclass
class CommandDecl:
    name: str
    usage: str
    summary: str
    group: str
    help: str
    klass: str
    session: bool = False
    #: It changes nothing: kern's MCP door offers it, and only such a command.
    read_only: bool = False
    #: When to use it, as kern's MCP door offers it (its catalog check refuses a read-only
    #: command without it).
    mcp: str = ""


@dataclass
class RequestDecl:
    """A request port, or an I/O component's verb: the request it sends and the answer it reads."""

    name: str
    type: str
    answer: str
    help: str


@dataclass
class Declaration:
    """A component.toml as the core reads it."""

    name: str
    help: str
    io: bool
    hash: str
    path: Path | None = None
    inputs: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, Port] = field(default_factory=dict)
    config: dict[str, Port] = field(default_factory=dict)
    commands: dict[str, CommandDecl] = field(default_factory=dict)
    requests: dict[str, RequestDecl] = field(default_factory=dict)
    verbs: dict[str, RequestDecl] = field(default_factory=dict)

    def derivations(self) -> list[str]:
        return sorted(p for p, o in self.outputs.items() if o.derived)


def read(path: str | Path) -> Declaration:
    """Read a component.toml, or the one in a component's folder."""
    p = Path(path)
    if p.is_dir():
        p = p / FILE
    d = parse(p.read_bytes())
    d.path = p
    return d


def parse(data: bytes) -> Declaration:
    """Read a component.toml's bytes, refusing what the core refuses."""
    try:
        doc = tomllib.loads(data.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise DeclarationError(f"declaration: {e}") from None
    errs: list[str] = []
    _keys(errs, doc, "", ("name", "contract", "io", "help", "inputs", "outputs", "config", "commands", "requests", "verbs"))
    name = doc.get("name")
    if not isinstance(name, str):
        errs.append("no name")
        name = ""
    if doc.get("contract") != CONTRACT or isinstance(doc.get("contract"), bool):
        errs.append(f"contract is {doc.get('contract')}, and this core speaks contract = {CONTRACT}")
    io = doc.get("io", False)
    if not isinstance(io, bool):
        errs.append("io is true or false")
    help_ = doc.get("help", "")
    if not all(_PORT.match(seg) for seg in name.split("/")):
        errs.append(f"a component needs a name of letters, digits and dashes, or <group>/<component>, not {_q(name)}")
    if not str(help_).strip():
        errs.append(f"component {name} has no help")
    d = Declaration(name=name, help=str(help_), io=bool(io), hash=digest(data))

    for port, t in sorted(_table(errs, doc, "inputs").items()):
        if not type_ok(t):
            errs.append(f"input {port}: {_q(t)} is no type: int, float, string, bool, [T], or a named shape such as github.issues")
            continue
        _name(errs, port, "input")
        d.inputs[port] = t
    for key, t in sorted(_table(errs, doc, "config").items()):
        p = _port(errs, t, f"config.{key}", key, ("type", "builtin", "help"))
        if p:
            _name(errs, key, "config key")
            _help(errs, p.help, f"config key {key}")
            d.config[key] = p
    for port, t in sorted(_table(errs, doc, "outputs").items()):
        where = f"outputs.{port}"
        p = _port(errs, t, where, port, ("type", "builtin", "help", "derived", "family"))
        if not p:
            continue
        p.derived, p.family = _flag(errs, t, where, "derived"), _flag(errs, t, where, "family")
        if p.derived and p.family:
            errs.append(f"{where}: a derivation writes no family")
        _name(errs, port, "output")
        _help(errs, p.help, f"output {port}")
        d.outputs[port] = p
    for n, t in sorted(_table(errs, doc, "commands").items()):
        where = f"commands.{_q(n)}"
        keys = ("usage", "summary", "group", "help", "class", "session", "read-only", "mcp")
        if not _sub(errs, t, where, keys):
            continue
        k = CommandDecl(name=n, usage=str(t.get("usage", "")), summary=str(t.get("summary", "")),
                        group=str(t.get("group", "")), help=str(t.get("help", "")),
                        klass=str(t.get("class", "")), session=_flag(errs, t, where, "session"),
                        read_only=_flag(errs, t, where, "read-only"), mcp=str(t.get("mcp", "")))
        for f in ("name", "usage", "summary", "help", "group"):
            if not str(getattr(k, f)).strip():
                errs.append(f'command "{n}" has no {f}')
        if k.klass not in ("interactive", "batch"):
            errs.append(f'command "{n}" has no class: interactive or batch')
        d.commands[n] = k
    for kind_, into, what in (("requests", d.requests, "request port"), ("verbs", d.verbs, "verb")):
        for n, t in sorted(_table(errs, doc, kind_).items()):
            where = f"{kind_}.{n}"
            if not _sub(errs, t, where, ("type", "answer", "help")):
                continue
            bad = [k for k in ("type", "answer") if not type_ok(t.get(k))]
            if bad:
                errs.extend(f"{where}: {k}: {_q(t.get(k))} is no type" for k in bad)
                continue
            _name(errs, n, what)
            _help(errs, t.get("help", ""), f"{what} {n}")
            into[n] = RequestDecl(name=n, type=t["type"], answer=t["answer"], help=str(t.get("help", "")))
    for port in d.requests:
        if port in d.inputs or port in d.outputs:
            errs.append(f"request port {port} is also an input or an output")
    for port in d.inputs:
        if port in d.outputs:
            errs.append(f"port {port} is both an input and an output")
    if d.verbs and not d.io:
        errs.append(f"component {name} accepts verbs but carries no I/O flag: only an I/O component reaches the outside")
    if errs:
        raise DeclarationError(f"component {name}: " + "; ".join(errs))
    return d


def _keys(errs: list[str], t: dict, where: str, allowed: tuple[str, ...]) -> None:
    for k in sorted(t):
        if k not in allowed:
            errs.append(f"no key {k}: a declaration holds {', '.join(allowed)}" if not where
                        else f"{where}: no key {k}: it holds {', '.join(allowed)}")


def _table(errs: list[str], doc: dict, key: str) -> dict:
    v = doc.get(key, {})
    if not isinstance(v, dict):
        errs.append(f"{key} is no table")
        return {}
    return v


def _sub(errs: list[str], t: object, where: str, allowed: tuple[str, ...]) -> bool:
    if not isinstance(t, dict):
        errs.append(f"{where} is no table")
        return False
    _keys(errs, t, where, allowed)
    return True


def _flag(errs: list[str], t: dict, where: str, key: str) -> bool:
    v = t.get(key, False)
    if not isinstance(v, bool):
        errs.append(f"{where}: {key} is true or false")
        return False
    return v


def _port(errs: list[str], t: object, where: str, name: str, allowed: tuple[str, ...]) -> Port | None:
    if not _sub(errs, t, where, allowed):
        return None
    assert isinstance(t, dict)
    typ = t.get("type")
    if not type_ok(typ):
        errs.append(f"{where}: type: {_q(typ)} is no type: int, float, string, bool, [T], or a named shape such as github.issues")
        return None
    if "builtin" not in t:
        errs.append(f"{where} has no built-in value")
        return None
    if not fits(t["builtin"], typ):
        errs.append(f"{where}: builtin takes {typ}, not {kind(t['builtin'])}")
        return None
    return Port(name=name, type=typ, builtin=t["builtin"], help=str(t.get("help", "")))


def _q(v: object) -> str:
    """A value as Go's %q quotes a string."""
    return json.dumps(v, ensure_ascii=False)


def _name(errs: list[str], n: str, what: str) -> None:
    if not _PORT.match(n):
        errs.append(f"{what} {_q(n)} needs a local name of letters, digits and dashes")


def _help(errs: list[str], h: object, what: str) -> None:
    if not str(h).strip():
        errs.append(f"{what} has no help")
