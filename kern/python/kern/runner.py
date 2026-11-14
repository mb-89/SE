"""The runner: a component's process, started from its ``component.toml``.

``python -m kern run <folder>`` reads the folder's ``component.toml``, imports the
folder's ``__init__.py``, which makes the component with :func:`kern.component`
and decorates its functions, and attaches it to the bus the core names in the
environment (``CORE_BUS``, ``CORE_USER``, ``CORE_TOKEN``), as docs/go-core.md,
"How a component in another language attaches", says:

1. it commits its attach on ``commit.<i>``: the contract and the declaration hash;
2. it hears ``run.<i>``, reads ``in.<i>`` and commits its derivations on ``commit.<i>``;
3. it answers each step of a command on ``cmd.<i>.<command>``, each in a thread
   of its own, so calls run side by side, and, an I/O component, each request on
   ``io.<i>.<verb>``; each line a step says goes out at once on
   ``say.<i>.<call>``, its own call's, and while a step runs it beats there, until
   its answer is out, so the core waits for a long step as long as the process
   lives, and an answer that is no JSON goes out as the step's error; a message on
   ``cmd.<i>.<command>`` without a reply, ``{"call", "stop"}``, is the core's
   stop word: it gave that call up, so the runner drops the call's waiting
   continuation and sets its :class:`Abandon`, which the call's code reads
   with :func:`abandoned`; one on ``io.<i>.<verb>`` without a reply,
   ``{"call", "stop"}``, names a request the core stopped waiting for, whose
   verb's code reads it the same way, and a request it names that has not run
   yet is answered as given up without running;
4. it beats on ``lease.<i>`` from its work loop, every 5 s.

It ends when the bus closes: the core ended it, or ended.
"""

from __future__ import annotations

import importlib.util
import json
import os
import queue
import sys
import threading
from pathlib import Path
from typing import Any

from . import declaration
from .component import Component, KernError, Result, _loaded
from .nats import Msg, NatsError, Peer
from .subjects import subject, token, word

#: How often the work loop beats on lease.<i>: the core's Beat.
BEAT = 5.0
#: How long a request to the core waits.
WAIT = 10.0


class Abandon:
    """The core's stop word for one call: set once, with its reason, when the core gives the call
    up (docs/go-core.md "A call given up"). The call's code reads it with :func:`abandoned`, and
    what waits on the call ends: it checks :attr:`event`, or runs a function :meth:`when` it comes."""

    def __init__(self) -> None:
        self.event = threading.Event()
        self.reason = ""
        self._lock = threading.Lock()
        self._then: list[Any] = []

    def when(self, fn) -> None:
        """Run ``fn(reason)`` once the call is given up: now, where it already is."""
        with self._lock:
            if not self.event.is_set():
                self._then.append(fn)
                return
        fn(self.reason)

    def set(self, reason: str) -> None:
        with self._lock:
            if self.event.is_set():
                return
            self.reason = reason
            self.event.set()
            then, self._then = self._then, []
        for fn in then:
            fn(reason)


_current = threading.local()


def abandoned() -> Abandon:
    """The :class:`Abandon` of the call this thread runs a step of, or of the request it serves on
    an I/O verb; outside a runner's step, one the core never sets, as the fake core gives no call
    up."""
    got = getattr(_current, "abandon", None)
    return got if got is not None else Abandon()


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
        self._abandons: dict[str, Abandon] = {}
        #: Each request on io.<i>.<verb> by its call, from its arrival until it is answered.
        self._asks: dict[str, Abandon] = {}
        self._steps_lock = threading.Lock()
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
        p.subscribe("cmd." + self.me + ".>", self._called)
        if self.comp.decl.io:
            p.subscribe("io." + self.me + ".>", self._asked)
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

    def _called(self, msg: Msg) -> None:
        if not msg.reply:  # no step: the core's stop word, {"call", "stop"}
            body = msg.json() or {}
            if "stop" in body:
                self._stop(str(body.get("call", "")), str(body["stop"]))
            return
        call = str((msg.json() or {}).get("call", ""))
        with self._steps_lock:  # before its thread starts, so a stop word that follows finds it
            self._abandons.setdefault(call, Abandon())
        # Each step runs in its own thread, so a long call never holds another; the steps of one
        # call never overlap, as the core asks the next only once the last has answered.
        threading.Thread(target=self._answer_step, args=(msg,), name="kern-step", daemon=True).start()

    def _asked(self, msg: Msg) -> None:
        """A request on io.<i>.<verb>, for the work loop, or the core's stop word for one, at once:
        the work loop may be serving the very request it ends."""
        body = msg.json() or {}
        call = str(body.get("call", ""))
        if not msg.reply:  # no request: the core's stop word, {"call", "stop"}
            if "stop" in body:
                with self._steps_lock:  # it stays until its request is answered (_handle)
                    abandon = self._asks.get(call)
                if abandon is not None:
                    abandon.set(str(body["stop"]))
            return
        if call:
            with self._steps_lock:
                self._asks.setdefault(call, Abandon())
        self._work.put(msg)

    def _answer_step(self, msg: Msg) -> None:
        try:
            self._handle(msg)
        except NatsError:
            if not self.peer.closed.is_set():
                raise

    def _stop(self, call: str, reason: str) -> None:
        """The core gave `call` up: drop its waiting continuation and tell its code."""
        with self._steps_lock:
            self._steps.pop(call, None)
            abandon = self._abandons.pop(call, None)
        if abandon is not None:
            abandon.set(reason)

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
            call = str(body.get("call", ""))
            with self._steps_lock:
                abandon = self._asks.get(call) or Abandon()
            if abandon.event.is_set():  # given up before it ran: nobody waits for its answer
                with self._steps_lock:
                    self._asks.pop(call, None)
                self.peer.respond(msg, {"error": f"the core gave it up: {abandon.reason}"})
                return
            _current.abandon = abandon
            try:
                self.peer.respond(msg, {"answer": self.comp.serve(what, body.get("request"))})
            except Exception as e:
                self.peer.respond(msg, {"error": str(e)})
            finally:
                _current.abandon = None
                with self._steps_lock:
                    self._asks.pop(call, None)
            return
        self._step(what, body, lambda answer: self.peer.respond(msg, answer))

    def _say(self, call: str, line: str | None = None) -> None:
        """One word on say.<i>.<call> for the step of `call`: a progress line, or a beat without one."""
        self.peer.publish("say." + self.me + "." + token(call), {} if line is None else {"line": line})

    def _step(self, name: str, body: dict[str, Any], send=None) -> dict[str, Any]:
        """Run one step of a command: each line it says goes to the core at once on say.<i>.<call>,
        and, while it runs, the runner beats there and on lease.<i> every BEAT, so the core
        waits for a long step as long as this process lives (docs/go-core.md "Progress and
        long calls"). With `send`, the step's answer goes out through it before the beat ends,
        so the core never waits in silence between the step's end and its answer; an answer
        that is no JSON goes out as the step's error instead of nothing."""
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
            answer = self._run_step(name, body, call, step)
            if send is not None:
                try:
                    data = json.dumps(answer)
                except (TypeError, ValueError) as e:
                    with self._steps_lock:  # no continuation runs after an answer the core never read
                        self._steps.pop(call, None)
                        self._abandons.pop(call, None)
                    answer = {"error": f"command {name!r}: its answer is no JSON: {e}"}
                    data = json.dumps(answer)
                send(data)
            return answer
        finally:
            done.set()

    def _run_step(self, name: str, body: dict[str, Any], call: str, step: int) -> dict[str, Any]:
        def say(line: str) -> None:
            self._say(call, str(line))

        with self._steps_lock:
            abandon = self._abandons.setdefault(call, Abandon())
        _current.abandon = abandon
        try:
            if step == 1:
                r = self.comp.run(name, body.get("args") or [], body.get("inputs") or {}, say)
            else:
                with self._steps_lock:
                    prev = self._steps.pop(call, None)
                if prev is None:
                    raise KernError(f"command {name!r}: call {call} has no step {step - 1} waiting")
                r = self.comp.then(prev, body.get("answers") or [])
        except Exception as e:
            with self._steps_lock:
                self._steps.pop(call, None)
                self._abandons.pop(call, None)
            return {"error": str(e)}
        finally:
            _current.abandon = None
        with self._steps_lock:
            if r.then is not None and not abandon.event.is_set():
                self._steps[call] = r
            else:  # the call ends here, or the core gave it up while this step ran
                self._abandons.pop(call, None)
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
