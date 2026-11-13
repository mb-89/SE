"""The fake core: a component tested alone, without the core or a bus.

    fake = Fake(tally)
    fake.seed(numbers=[1, 2, 3], scale=2)    # inputs and config by local name
    fake.derive("total")
    assert fake.out("total").value == 12
    fake.answer("post", lambda line: 1)       # each request's answer, as the verb would give it
    text = fake.run("tally file", "x")
    assert fake.requests == [Ask("post", "x")]

It speaks the component contract and nothing more, as the Go fake, ``kerntest``,
does; ``contract/cases.json`` holds both, and the real core, to one suite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .component import Ask, Component, KernError, Result
from .declaration import CONFIG_PREFIX


@dataclass(frozen=True)
class Value:
    """What an output reads: its value, and whether the component committed it."""

    value: Any
    provided: bool


class Fake:
    """One component's inputs, committed outputs and requests, by local name."""

    def __init__(self, comp: Component):
        comp.check()
        self.component = comp
        d = comp.decl
        self._seeded: dict[str, Any] = {CONFIG_PREFIX + k: c.builtin for k, c in d.config.items()}
        self._out: dict[str, Any] = {}
        self._answers: dict[str, Callable[[Any], Any]] = {}
        #: The requests the component made and that were answered, in order.
        self.requests: list[Ask] = []
        #: The progress lines every command run so far said, in order.
        self.lines: list[str] = []

    def seed(self, values: dict[str, Any] | None = None, /, **kw: Any) -> None:
        """Set what input ports and config keys read, by local name; one never seeded reads its built-in value."""
        d = self.component.decl
        for port, v in {**(values or {}), **kw}.items():
            if port in d.inputs:
                self._seed_port(port, d.inputs[port], v)
            elif port in d.config:
                self._seed_port(CONFIG_PREFIX + port, d.config[port].type, v)
            else:
                raise KernError(f"component {d.name} reads no input or config key {port!r}")

    def config(self, values: dict[str, Any] | None = None, /, **kw: Any) -> None:
        """Set config keys' values; one never set is the key's built-in value."""
        d = self.component.decl
        for key, v in {**(values or {}), **kw}.items():
            if key not in d.config:
                raise KernError(f"component {d.name} has no config key {key!r}")
            self._seed_port(CONFIG_PREFIX + key, d.config[key].type, v)

    def _seed_port(self, port: str, typ: str, v: Any) -> None:
        from .declaration import fits, kind

        if not fits(v, typ):
            raise KernError(f"input {port} takes {typ}, not {kind(v)}")
        self._seeded[port] = v

    def answer(self, port: str, fn: Callable[[Any], Any]) -> None:
        """Hand a request port the function that answers every request on it; raising fails the request."""
        if port not in self.component.decl.requests:
            raise KernError(f"component {self.component.name} has no request port {port!r}")
        self._answers[port] = fn

    def inputs(self) -> dict[str, Any]:
        """The inputs a run reads, by local port, as the core sends them."""
        d = self.component.decl
        out = {p: self._seeded.get(p) for p in d.inputs}
        out.update({CONFIG_PREFIX + k: self._seeded[CONFIG_PREFIX + k] for k in d.config})
        return out

    def derive(self, port: str) -> None:
        """Run the derivation of an output and commit what it answers."""
        self._out[port] = self.component.derive(port, self.inputs())

    def run(self, name: str, *args: str, say: Callable[[str], None] | None = None) -> str:
        """Run a command: commit each step's writes, answer its requests in order, hand the answers to its
        continuation. A failed request stops it with its reason; it answers every step's text, one line each.
        Each line it says joins ``lines`` and goes to ``say``, the call's own caller, where given: calls
        that run side by side, each in its own thread, so each hear their own."""
        text: list[str] = []

        def said(line: str) -> None:
            self.lines.append(line)
            if say is not None:
                say(line)

        try:
            r: Result = self.component.run(name, list(args), self.inputs(), said)
        except Exception as e:
            raise KernError(str(e)) from e
        while True:
            if r.text:
                text.append(r.text)
            for w in r.writes:
                at = _at(w.port, w.key)
                if w.gone:
                    self._out.pop(at, None)
                else:
                    self._out[at] = w.value
            answers = []
            for i, a in enumerate(r.requests, 1):
                try:
                    ans = self._answer(a)
                except Exception as e:
                    raise KernError(f"{name}: request {i} of {len(r.requests)}, on {a.port}, failed: {e}", "\n".join(text)) from e
                self.requests.append(a)
                answers.append(ans)
            if r.then is None:
                return "\n".join(text)
            try:
                r = self.component.then(r, answers)
            except Exception as e:
                raise KernError(str(e), "\n".join(text)) from e

    def _answer(self, a: Ask) -> Any:
        from .declaration import fits, kind

        fn = self._answers.get(a.port)
        if fn is None:
            raise KernError(f"request port {a.port} has no answer: hand it one with answer")
        v = fn(a.value)
        want = self.component.decl.requests[a.port].answer
        if not fits(v, want):
            raise KernError(f"request port {a.port} reads {want}, and its answerer gave {kind(v)}")
        return v

    def out(self, port: str, key: str = "") -> Value:
        """What the component committed to an output, at key for a family, or its built-in value."""
        o = self.component.decl.outputs.get(port)
        if o is None:
            raise KernError(f"component {self.component.name} writes no output {port!r}")
        if o.family != bool(key):
            raise KernError(f"output {port} of component {self.component.name}: a family is read at a key, and only a family")
        at = _at(port, key)
        if at in self._out:
            return Value(self._out[at], True)
        return Value(o.builtin, False)


def _at(port: str, key: str) -> str:
    return f"{port}/{key}" if key else port
