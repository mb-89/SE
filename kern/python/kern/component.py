"""A component in Python: its declaration and the functions that answer it.

    from kern import component

    tally = component("tally")            # reads component.toml beside this file

    @tally.derived("total")
    def total(numbers, config):
        return sum(numbers or []) * config["scale"]

    @tally.command("tally note")
    def note(args, inputs, say):
        say("Phase: noting")
        return tally.result(f"noted {' '.join(args)}", writes=[tally.set("note", " ".join(args))])

A derivation is handed its inputs by keyword (a port's dashes as underscores)
and ``config``, the config keys by name, where its signature names them. A
command is handed its arguments, its inputs (a dict by local port, with
``inputs.config``) and ``say``, which adds a progress line. It answers a text,
or a :class:`Result` with the writes, the requests and a continuation that
reads the requests' answers. The core and the fake core run both alike.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import declaration
from .declaration import CONFIG_PREFIX, Declaration


@dataclass(frozen=True)
class Write:
    """One value a run commits to one of its component's outputs; a family's stands at its key."""

    port: str
    value: Any = None
    key: str = ""
    gone: bool = False

    def wire(self) -> dict:
        w: dict[str, Any] = {"port": self.port}
        if self.key:
            w["key"] = self.key
        if self.gone:
            w["gone"] = True
        else:
            w["value"] = self.value
        return w


@dataclass(frozen=True)
class Ask:
    """One request a command makes on one of its local request ports."""

    port: str
    value: Any = None


@dataclass
class Result:
    """What a command, or one of its continuations, answers."""

    text: str = ""
    writes: list[Write] = field(default_factory=list)
    requests: list[Ask] = field(default_factory=list)
    then: Callable[[list[Any]], "Result | str"] | None = None


class Inputs(dict):
    """A command's inputs by local port; ``config`` holds its config keys by name."""

    def __init__(self, ports: dict[str, Any], config: dict[str, Any]):
        super().__init__(ports)
        self.config = config


class KernError(Exception):
    """A run the core refuses or that failed; ``text`` is what its steps said before."""

    def __init__(self, message: str, text: str = ""):
        super().__init__(message)
        self.text = text


class Component:
    """A component's declaration and the functions that answer its derivations, commands and verbs."""

    def __init__(self, decl: Declaration):
        self.decl = decl
        self.name = decl.name
        self._derive: dict[str, Callable[..., Any]] = {}
        self._commands: dict[str, Callable[..., Any]] = {}
        self._verbs: dict[str, Callable[[Any], Any]] = {}

    # Declaring the functions.

    def derived(self, port: str) -> Callable:
        """Decorate the function that derives an output declared ``derived = true``."""
        o = self.decl.outputs.get(port)
        if o is None or not o.derived:
            raise KernError(f"component {self.name} declares no derived output {port!r}")
        return self._register(self._derive, port)

    def command(self, name: str) -> Callable:
        """Decorate the function that answers a declared command."""
        if name not in self.decl.commands:
            raise KernError(f"component {self.name} declares no command {name!r}")
        return self._register(self._commands, name)

    def verb(self, name: str) -> Callable:
        """Decorate the function that answers a verb of a declared I/O component."""
        if name not in self.decl.verbs:
            raise KernError(f"component {self.name} declares no verb {name!r}")
        return self._register(self._verbs, name)

    def _register(self, into: dict, key: str) -> Callable:
        def decorate(fn: Callable) -> Callable:
            if key in into:
                raise KernError(f"component {self.name}: {key!r} has two functions")
            into[key] = fn
            return fn
        return decorate

    def check(self) -> None:
        """Refuse a component a declared derivation, command or verb has no function for."""
        missing = [f"derivation {p}" for p in self.decl.derivations() if p not in self._derive]
        missing += [f"command {n!r}" for n in self.decl.commands if n not in self._commands]
        missing += [f"verb {v}" for v in self.decl.verbs if v not in self._verbs]
        if missing:
            raise KernError(f"component {self.name} declares {', '.join(missing)}, and no function answers it")

    # Making writes and requests.

    def set(self, port: str, value: Any) -> Write:
        return Write(port=port, value=value)

    def at(self, port: str, key: str, value: Any) -> Write:
        return Write(port=port, value=value, key=key)

    def drop(self, port: str, key: str) -> Write:
        return Write(port=port, key=key, gone=True)

    def ask(self, port: str, value: Any) -> Ask:
        return Ask(port=port, value=value)

    @staticmethod
    def result(text: str = "", writes: list[Write] | None = None, requests: list[Ask] | None = None,
               then: Callable[[list[Any]], Result | str] | None = None) -> Result:
        return Result(text=text, writes=list(writes or []), requests=list(requests or []), then=then)

    # Running: what the fake core and the runner both call.

    def split(self, inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """A run's inputs as the core sends them, by local port, split into inputs and config."""
        ports = {p: inputs.get(p) for p in self.decl.inputs}
        config = {k: inputs.get(CONFIG_PREFIX + k, c.builtin) for k, c in self.decl.config.items()}
        return ports, config

    def derive(self, port: str, inputs: dict[str, Any]) -> Any:
        """Run the derivation of an output on a run's inputs; refuse an answer of another type."""
        fn = self._derive.get(port)
        if fn is None:
            raise KernError(f"component {self.name} derives no output {port!r}")
        ports, config = self.split(inputs)
        kw = {p.replace("-", "_"): v for p, v in ports.items()}
        kw["config"] = config
        params = inspect.signature(fn).parameters
        if not any(p.kind is p.VAR_KEYWORD for p in params.values()):
            kw = {k: v for k, v in kw.items() if k in params}
        value = fn(**kw)
        o = self.decl.outputs[port]
        if not declaration.fits(value, o.type):
            raise KernError(f"component {self.name}: derivation {port} answers {declaration.kind(value)}, and output {port} takes {o.type}")
        return value

    def run(self, name: str, args: list[str], inputs: dict[str, Any], say: Callable[[str], None]) -> Result:
        """Run a command's first step."""
        fn = self._commands.get(name)
        if fn is None:
            raise KernError(f"component {self.name} has no command {name!r}")
        ports, config = self.split(inputs)
        return self.checked(fn(list(args), Inputs(ports, config), say))

    def then(self, step: Result, answers: list[Any]) -> Result:
        """Run a continuation on the answers of its step's requests."""
        assert step.then is not None
        return self.checked(step.then(answers))

    def checked(self, r: Result | str | None) -> Result:
        """A step's answer as a Result, refused where it breaks the contract as the core refuses it."""
        if r is None:
            r = Result()
        elif isinstance(r, str):
            r = Result(text=r)
        elif not isinstance(r, Result):
            raise KernError(f"component {self.name}: a command answers a text or a Result, not {type(r).__name__}")
        self.check_writes(r.writes)
        self.check_asks(r.requests)
        return r

    def check_writes(self, writes: list[Write], derived: bool = False) -> None:
        for w in writes:
            o = self.decl.outputs.get(w.port)
            if o is None:
                raise KernError(f'component {self.name} writes no output "{w.port}"')
            if o.derived and not derived:
                raise KernError(f"component {self.name}: output {w.port} is written by its derivation alone")
            if w.gone and not o.family:
                raise KernError(f"component {self.name}: output {w.port} is no family, and drops no key")
            if not w.gone and not declaration.fits(w.value, o.type):
                raise KernError(f"component {self.name}: output {w.port} takes {o.type}, not {declaration.kind(w.value)}")
            if o.family and not _key(w.key):
                raise KernError(f"component {self.name}: output {w.port} is a family, and {w.key!r} is no key: letters, digits, dots, dashes and underscores")
            if not o.family and w.key:
                raise KernError(f"component {self.name}: output {w.port} is no family, and takes no key")

    def check_asks(self, asks: list[Ask]) -> None:
        for a in asks:
            r = self.decl.requests.get(a.port)
            if r is None:
                raise KernError(f'component {self.name} has no request port "{a.port}"')
            if not declaration.fits(a.value, r.type):
                raise KernError(f"component {self.name}: request port {a.port} sends {r.type}, not {declaration.kind(a.value)}")

    def serve(self, verb: str, req: Any) -> Any:
        """Answer one request on a verb, as the I/O component's outside thing answers it."""
        fn = self._verbs.get(verb)
        v = self.decl.verbs.get(verb)
        if fn is None or v is None:
            raise KernError(f"component {self.name} accepts no verb {verb!r}")
        if not declaration.fits(req, v.type):
            raise KernError(f"component {self.name}: verb {verb} takes {v.type}, not {declaration.kind(req)}")
        return fn(req)


def _key(s: str) -> bool:
    return bool(s) and s not in (".", "..") and all(c.isascii() and (c.isalnum() or c in "-._") for c in s)


def component(name: str, path: str | Path | None = None) -> Component:
    """The component of that name, from the component.toml at path, or beside the caller's file."""
    if path is None:
        caller = inspect.stack()[1].filename
        path = Path(caller).resolve().parent
    decl = declaration.read(path)
    if decl.name != name:
        raise KernError(f"{decl.path} declares the component {decl.name}, not {name}")
    c = Component(decl)
    _loaded[str(Path(decl.path).resolve())] = c  # type: ignore[arg-type]
    return c


#: Every component made so far, by its declaration's path: the runner finds its component here.
_loaded: dict[str, Component] = {}
