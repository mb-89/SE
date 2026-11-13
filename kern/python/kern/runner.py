"""The runner: a component's process, started from its ``component.toml``.

``python -m kern run <folder>`` reads the folder's ``component.toml``, imports the
folder's ``__init__.py``, which makes the component with :func:`kern.component`
and decorates its functions, and attaches it to the bus the core names in the
environment (``CORE_BUS``, ``CORE_USER``, ``CORE_TOKEN``), as docs/go-core.md,
"How a component in another language attaches", says:

1. it commits its attach on ``commit.<i>``: the contract and the declaration hash;
2. it hears ``run.<i>``, reads ``in.<i>`` and commits its derivations on ``commit.<i>``;
3. it answers each step of a command on ``cmd.<i>.<command>`` and, an I/O
   component, each request on ``io.<i>.<verb>``; each line a step says goes out
   at once on ``say.<i>``, and while a step runs it beats there, so the core
   waits for a long step as long as the process lives;
4. it beats on ``lease.<i>`` from its work loop, every 5 s.

It ends when the bus closes: the core ended it, or ended.
"""

from __future__ import annotations

import importlib.util
import os
import queue
import sys
import threading
from pathlib import Path
from typing import Any

from . import declaration
from .component import Component, KernError, Result, _loaded
from .nats import Msg, NatsError, Peer
from .subjects import subject, word

#: How often the work loop beats on lease.<i>: the core's Beat.
BEAT = 5.0
#: How long a request to the core waits.
WAIT = 10.0


def load(folder: str | Path) -> Component:
    """The component of a folder: its component.toml, and the functions its __init__.py decorates."""
    folder = Path(folder).resolve()
    decl = declaration.read(folder)
    init = folder / "__init__.py"
    if not init.is_file():
        raise KernError(f"{folder} holds no __init__.py that makes the component {decl.name}")
    modname = "kern_component_" + "".join(c if c.isalnum() else "_" for c in decl.name)
    spec = importlib.util.spec_from_file_location(modname, init, submodule_search_locations=[str(folder)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[modname] = module
    spec.loader.exec_module(module)
    comp = _loaded.get(str((folder / declaration.FILE).resolve()))
    if comp is None:
        raise KernError(f"{init} makes no component from {folder / declaration.FILE}: call kern.component({decl.name!r})")
    comp.check()
    return comp


class Runner:
    """One declared instance's process on the bus."""

    def __init__(self, comp: Component, peer: Peer, instance: str):
        self.comp = comp
        self.peer = peer
        self.instance = instance
        self.me = subject(instance)
        self._work: queue.Queue[Msg | None] = queue.Queue()
        self._steps: dict[str, Result] = {}
        self._run_due = threading.Event()

    def attach(self) -> None:
        """Commit the attach; raise where the core refuses it."""
        a = self.peer.request("commit." + self.me, {"attach": {"contract": declaration.CONTRACT, "hash": self.comp.decl.hash}}, WAIT).json()
        if not a or not a.get("accepted"):
            raise KernError(f"the core refuses the attach of {self.instance}: {(a or {}).get('refused', a)}")

    def serve(self) -> None:
        """Hear the instance's subjects, attach, and work until the bus closes."""
        p = self.peer
        p.subscribe("run." + self.me, self._due)
        p.subscribe("cmd." + self.me + ".>", self._work.put)
        if self.comp.decl.io:
            p.subscribe("io." + self.me + ".>", self._work.put)
        p.flush()
        self.attach()
        p.publish("lease." + self.me)
        threading.Thread(target=self._watch, daemon=True).start()
        while True:
            try:
                msg = self._work.get(timeout=BEAT)
            except queue.Empty:
                msg = ...  # type: ignore[assignment]
            if msg is None or p.closed.is_set():
                return
            try:
                if self._run_due.is_set():
                    self._run_due.clear()
                    self._derive()
                if isinstance(msg, Msg):
                    self._handle(msg)
                p.publish("lease." + self.me)
            except NatsError:
                if p.closed.is_set():
                    return
                raise

    def _watch(self) -> None:
        self.peer.closed.wait()
        self._work.put(None)

    def _due(self, _msg: Msg) -> None:
        # The reader thread only marks it: the work loop reads in.<i> and commits.
        self._run_due.set()
        self._work.put(...)  # type: ignore[arg-type]

    def _derive(self) -> None:
        got = self.peer.request("in." + self.me, {}, WAIT).json() or {}
        if "error" in got:
            raise KernError(f"in.{self.me}: {got['error']}")
        inputs = got.get("inputs", {})
        writes = []
        for port in self.comp.decl.derivations():
            try:
                writes.append({"port": port, "value": self.comp.derive(port, inputs)})
            except Exception as e:  # one derivation's failure leaves the others' values standing
                print(f"kern: {self.instance}: derivation {port} failed: {e}", file=sys.stderr, flush=True)
        if writes:
            a = self.peer.request("commit." + self.me, {"writes": writes}, WAIT).json() or {}
            if not a.get("accepted"):
                print(f"kern: {self.instance}: the core refuses the derivations' commit: {a.get('refused')}", file=sys.stderr, flush=True)

    def _handle(self, msg: Msg) -> None:
        verb, _, rest = msg.subject.partition(".")
        what = word(rest[len(self.me) + 1:])
        body = msg.json() or {}
        if verb == "io":
            try:
                self.peer.respond(msg, {"answer": self.comp.serve(what, body.get("request"))})
            except Exception as e:
                self.peer.respond(msg, {"error": str(e)})
            return
        self.peer.respond(msg, self._step(what, body))

    def _say(self, call: str, line: str | None = None) -> None:
        """One word on say.<i> for the step of `call`: a progress line, or a beat without one."""
        self.peer.publish("say." + self.me, {"call": call} if line is None else {"call": call, "line": line})

    def _step(self, name: str, body: dict[str, Any]) -> dict[str, Any]:
        """Run one step of a command: each line it says goes to the core at once on say.<i>,
        and, while it runs, the runner beats there and on lease.<i> every BEAT, so the core
        waits for a long step as long as this process lives (docs/go-core.md "Progress and
        long calls")."""
        call, step = str(body.get("call", "")), int(body.get("step", 1))
        done = threading.Event()

        def beat() -> None:
            while not done.wait(BEAT):
                try:
                    self._say(call)
                    self.peer.publish("lease." + self.me)
                except NatsError:
                    return

        threading.Thread(target=beat, name="kern-step-beat", daemon=True).start()
        try:
            return self._run_step(name, body, call, step)
        finally:
            done.set()

    def _run_step(self, name: str, body: dict[str, Any], call: str, step: int) -> dict[str, Any]:
        def say(line: str) -> None:
            self._say(call, str(line))

        try:
            if step == 1:
                r = self.comp.run(name, body.get("args") or [], body.get("inputs") or {}, say)
            else:
                prev = self._steps.pop(call, None)
                if prev is None:
                    raise KernError(f"command {name!r}: call {call} has no step {step - 1} waiting")
                r = self.comp.then(prev, body.get("answers") or [])
        except Exception as e:
            self._steps.pop(call, None)
            return {"error": str(e)}
        if r.then is not None:
            self._steps[call] = r
        return {"text": r.text, "writes": [w.wire() for w in r.writes],
                "requests": [{"port": a.port, "value": a.value} for a in r.requests], "then": r.then is not None}


def main(argv: list[str] | None = None) -> int:
    """``python -m kern run <folder>``: run the folder's component as the instance the environment names."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] != "run":
        print("usage: python -m kern run <component folder>", file=sys.stderr)
        return 2
    try:
        comp = load(args[1])
        env = {k: os.environ.get(k, "") for k in ("CORE_BUS", "CORE_USER", "CORE_TOKEN")}
        if not all(env.values()):
            raise KernError("the core names no bus: CORE_BUS, CORE_USER and CORE_TOKEN are its placement's")
        peer = Peer(env["CORE_BUS"], env["CORE_USER"], env["CORE_TOKEN"], name=comp.name)
        Runner(comp, peer, env["CORE_USER"]).serve()
    except (KernError, NatsError, declaration.DeclarationError, OSError) as e:
        print(f"kern: {e}", file=sys.stderr, flush=True)
        return 1
    return 0
