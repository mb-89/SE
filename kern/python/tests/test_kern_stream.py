"""The Python SDK's half of streaming (docs/go-core.md "Progress and long calls"): a step's lines go
out at once on ``say.<i>.<call>``, and while a step runs the runner beats there and on ``lease.<i>``, so the
core waits for a long step as long as the process lives. ``contract/stream_test.go`` runs the same
runner against the real core."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

KERN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KERN / "python"))

from kern import runner  # noqa: E402

DECLARATION = """name = "drip"
contract = 1
help = "Drips progress lines."

[commands."drip talk"]
usage = "drip talk"
summary = "Say two lines, slowly."
group = "Fixtures"
help = "Says each line as it goes."
class = "batch"
"""

INIT = """import time
from kern import component

drip = component("drip")


@drip.command("drip talk")
def talk(args, inputs, say):
    say("one")
    time.sleep(0.6)
    say("two")
    return "done"
"""


class Peer:
    """What the runner publishes, in order, from any thread."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.lock = threading.Lock()
        self.closed = threading.Event()

    def publish(self, subject: str, data=b"", reply: str = "") -> None:
        with self.lock:
            self.sent.append((subject, data if isinstance(data, dict) else json.loads(data or b"{}")))


def test_a_step_says_its_lines_at_once_and_beats_while_it_runs(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "component.toml").write_text(DECLARATION, encoding="utf-8")
    (tmp_path / "__init__.py").write_text(INIT, encoding="utf-8")
    comp = runner.load(tmp_path)
    monkeypatch.setattr(runner, "BEAT", 0.1)
    peer = Peer()
    run = runner.Runner(comp, peer, "drip")  # type: ignore[arg-type]

    answer = run._step("drip talk", {"call": "7", "step": 1, "args": []})

    assert answer["text"] == "done" and "lines" not in answer, answer
    said = [body for subject, body in peer.sent if subject == "say.drip.7"]
    assert [b["line"] for b in said if "line" in b] == ["one", "two"]
    assert not [s for s, _ in peer.sent if s.startswith("say.") and s != "say.drip.7"], \
        "a step says its words on its own call's subject alone"
    beats = [b for b in said if "line" not in b]
    assert beats, "the runner beats on say.drip.7 while the step runs"
    leases = [subject for subject, _ in peer.sent if subject == "lease.drip"]
    assert len(leases) == len(beats), "each beat also renews the lease"
    two = next(i for i, (s, b) in enumerate(peer.sent) if b.get("line") == "two")
    assert any(s == "say.drip.7" and "line" not in b for s, b in peer.sent[:two]), \
        "a beat comes between the lines, while the step sleeps"
    before = len(peer.sent)
    time.sleep(0.3)
    assert len(peer.sent) == before, "no beat after the step answered"


HOLD = """name = "hold"
contract = 1
help = "Holds a call until its continuation runs."

[commands."hold on"]
usage = "hold on NAME"
summary = "Ask once, then answer."
group = "Fixtures"
help = "Asks its ledger, and answers the answer."
class = "batch"

[requests.ask]
type = "string"
answer = "string"
help = "The question."
"""

HOLD_INIT = """from kern import abandoned, component

hold = component("hold")
given = {}


@hold.command("hold on")
def on(args, inputs, say):
    name = args[0]
    abandoned().when(lambda reason: given.setdefault(name, reason))
    return hold.result(requests=[hold.ask("ask", name)], then=lambda answers: f"{name}: {answers[0]}")
"""


def test_the_cores_stop_word_gives_up_one_call_and_leaves_the_call_beside_it(tmp_path: Path) -> None:
    """The core's stop word, a cmd.<i>.<command> message without a reply that names the call and
    the reason: the runner drops that call's waiting continuation and sets its Abandon, which the
    call's code read with kern.abandoned(); the call beside it keeps its continuation and answers."""
    from kern.nats import Msg
    from kern.subjects import token

    (tmp_path / "component.toml").write_text(HOLD, encoding="utf-8")
    (tmp_path / "__init__.py").write_text(HOLD_INIT, encoding="utf-8")
    comp = runner.load(tmp_path)
    run = runner.Runner(comp, Peer(), "hold")  # type: ignore[arg-type]
    module = sys.modules["kern_component_hold"]
    subject = "cmd.hold." + token("hold on")
    for call, name in (("1", "a"), ("2", "b")):
        assert run._step("hold on", {"call": call, "step": 1, "args": [name]})["then"] is True
    assert sorted(run._steps) == ["1", "2"]

    run._called(Msg(subject, "", json.dumps({"call": "1", "stop": "its caller gave it up"}).encode()))

    assert module.given == {"a": "its caller gave it up"}
    assert sorted(run._steps) == ["2"], "only the given-up call's continuation is dropped"
    assert run._step("hold on", {"call": "1", "step": 2, "answers": ["late"]}) == {
        "error": "command 'hold on': call 1 has no step 1 waiting"}
    assert run._step("hold on", {"call": "2", "step": 2, "answers": ["yes"]})["text"] == "b: yes"
    assert module.given == {"a": "its caller gave it up"} and not run._steps and not run._abandons


def test_a_caller_that_stops_waiting_gives_its_call_up(monkeypatch) -> None:
    """Peer.request with give_up, and Peer.call: a call.<command> the caller stops waiting for is
    given up on call.core.abandon, naming the call by its reply subject; one that answered is not."""
    from kern import nats

    peer = object.__new__(nats.Peer)
    peer._inbox, peer._next, peer._waiting, peer._progress = "_INBOX.c", iter(range(1, 99)), {}, {}
    peer.closed = threading.Event()
    sent: list[tuple[str, dict, str]] = []

    def publish(subject, data=b"", reply=""):
        sent.append((subject, data, reply))
        if subject == nats.ABANDON:
            got = peer._waiting[reply]
            got[1].append(nats.Msg(reply, "", json.dumps({"abandoned": True}).encode()))
            got[0].set()

    monkeypatch.setattr(peer, "publish", publish)
    try:
        peer.request("call.slow", {"args": []}, 0.2, give_up=True)
    except nats.NatsError as error:
        assert "answers nothing within 0.2 s" in str(error)
    else:
        raise AssertionError("a silent call answers")
    assert sent[1][:2] == (nats.ABANDON, {"call": "_INBOX.c.1"}), sent
    sent.clear()
    try:
        peer.call("call.long", {"args": []}, lambda m: None, idle=0.2)
    except nats.NatsError:
        pass
    assert [s for s, _, _ in sent] == ["call.long", nats.ABANDON]
    assert sent[1][1] == {"call": sent[0][2]}
    sent.clear()
    try:
        peer.request("call.quick", {}, 0.2)
    except nats.NatsError:
        pass
    assert [s for s, _, _ in sent] == ["call.quick"], "without give_up, nothing is given up"


DESK = """name = "desk"
contract = 1
io = true
help = "Answers questions."

[verbs.answer]
type = "string"
answer = "string"
help = "Answers a question once its call is given up."
"""

DESK_INIT = """from kern import abandoned, component

desk = component("desk")
started = __import__("threading").Event()


@desk.verb("answer")
def answer(question):
    started.set()
    given = abandoned()
    if not given.event.wait(10):
        return "never given up"
    return f"{question}: {given.reason}"
"""


class Answering(Peer):
    """A Peer that also records the runner's answers to requests."""

    def __init__(self) -> None:
        super().__init__()
        self.answered: list[tuple[str, dict]] = []

    def respond(self, msg, data) -> None:
        with self.lock:
            self.answered.append((msg.reply, data))


def test_the_cores_stop_word_on_a_verb_ends_the_request_it_names(tmp_path: Path) -> None:
    """The core's stop word on io.<i>.<verb>, a message without a reply that names the request's
    call: the verb serving it reads it with kern.abandoned() and ends, and a request it names
    before it runs is answered as given up without running."""
    from kern.nats import Msg

    (tmp_path / "component.toml").write_text(DESK, encoding="utf-8")
    (tmp_path / "__init__.py").write_text(DESK_INIT, encoding="utf-8")
    comp = runner.load(tmp_path)
    peer = Answering()
    run = runner.Runner(comp, peer, "desk")  # type: ignore[arg-type]
    module = sys.modules["kern_component_desk"]
    subject = "io.desk.answer"

    def request(call: str) -> Msg:
        return Msg(subject, f"_INBOX.r{call}", json.dumps({"call": call, "request": "q" + call}).encode())

    def stop(call: str) -> Msg:
        return Msg(subject, "", json.dumps({"call": call, "stop": "its caller gave it up"}).encode())

    # Given up while its verb runs: the verb ends with the reason.
    first = request("1")
    run._asked(first)
    assert run._work.get_nowait() is first
    serving = threading.Thread(target=run._handle, args=(first,))
    serving.start()
    assert module.started.wait(10)
    run._asked(stop("1"))
    serving.join(10)
    assert peer.answered == [("_INBOX.r1", {"answer": "q1: its caller gave it up"})]
    # Given up before it runs: answered as given up, its verb never runs.
    module.started.clear()
    second = request("2")
    run._asked(second)
    run._asked(stop("2"))
    run._handle(run._work.get_nowait())
    assert peer.answered[1] == ("_INBOX.r2", {"error": "the core gave it up: its caller gave it up"})
    assert not module.started.is_set() and not run._asks


ODD = """name = "odd"
contract = 1
help = "Answers what JSON cannot carry."

[commands."odd ask"]
usage = "odd ask"
summary = "Ask with a value JSON cannot carry."
group = "Fixtures"
help = "Asks its ledger with a set."
class = "batch"

[requests.ask]
type = "odd.question"
answer = "string"
help = "The question."
"""

ODD_INIT = """from kern import component

odd = component("odd")


@odd.command("odd ask")
def ask(args, inputs, say):
    return odd.result(requests=[odd.ask("ask", {"labels": {"pause"}})], then=lambda answers: "never")
"""


def test_a_step_answers_while_it_beats_and_an_answer_that_is_no_json_as_its_error(
        tmp_path: Path, monkeypatch) -> None:
    """The step's answer goes out before its beat ends, so the core never waits in silence between
    the step's end and its answer; an answer JSON cannot carry goes out as the step's error, with no
    continuation left waiting, where before nothing went out and the core waited out its StepWait."""
    (tmp_path / "component.toml").write_text(ODD, encoding="utf-8")
    (tmp_path / "__init__.py").write_text(ODD_INIT, encoding="utf-8")
    comp = runner.load(tmp_path)
    monkeypatch.setattr(runner, "BEAT", 0.05)
    peer = Peer()
    run = runner.Runner(comp, peer, "odd")  # type: ignore[arg-type]
    sent: list[dict] = []

    def respond(msg, data) -> None:  # a slow answer, encoded as Peer.publish encodes it
        data = json.dumps(data) if isinstance(data, (dict, list)) else data
        before = len(peer.sent)
        time.sleep(0.3)
        assert len(peer.sent) > before, "the runner beats until the answer is out"
        sent.append(json.loads(data))

    peer.respond = respond  # type: ignore[attr-defined]
    from kern.nats import Msg
    from kern.subjects import token

    run._handle(Msg("cmd.odd." + token("odd ask"), "_INBOX.core.1",
                    json.dumps({"call": "3", "step": 1, "args": []}).encode()))

    assert len(sent) == 1 and "is no JSON" in sent[0]["error"], sent
    assert not run._steps and not run._abandons
