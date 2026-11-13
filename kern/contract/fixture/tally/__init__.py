"""The contract suite's fixture component in Python: tally, as contract/fixture.go answers it in Go."""

import threading

from kern import component

tally = component("tally")

#: How long tally meet waits for another call: calls that ran one after the other never meet.
MEET_WAIT = 10.0
_meeting = threading.Lock()
_waiting: list[tuple[str, threading.Event, list[str]]] = []


@tally.derived("total")
def total(numbers, config):
    return sum(numbers or []) * config["scale"]


@tally.command("tally note")
def note(args, inputs, say):
    say("Phase: noting")
    if not args:
        raise ValueError("tally note takes the words to keep")
    words = " ".join(args)
    count = len(inputs["numbers"] or [])
    return tally.result(f'noted "{words}" beside {count} numbers', writes=[tally.set("note", words)])


@tally.command("tally file")
def file(args, inputs, say):
    def filed(answers):
        if not answers:
            return "nothing filed"
        entry = f"{args[-1]} as line {answers[-1]}"
        return tally.result("filed " + entry, writes=[tally.set("note", entry)])

    began = f"filing {len(args)} words"
    return tally.result(began, writes=[tally.set("note", began)],
                        requests=[tally.ask("post", a) for a in args], then=filed)


@tally.command("tally stray")
def stray(args, inputs, say):
    return tally.result(writes=[tally.set("nowhere", "x")])


@tally.command("tally wrong")
def wrong(args, inputs, say):
    return tally.result(writes=[tally.set("note", 7)])


@tally.command("tally meet")
def meet(args, inputs, say):
    name = args[0]
    say(f"Phase: {name} waits")
    other = _meet(name)
    say(f"Phase: {name} met {other}")
    return f"{name} met {other}"


def _meet(name):
    """The name of the other call of tally meet, once both are running; refused after MEET_WAIT."""
    with _meeting:
        if _waiting:
            other, arrived, mine = _waiting.pop()
            mine.append(name)
            arrived.set()
            return other
        arrived, theirs = threading.Event(), []
        _waiting.append((name, arrived, theirs))
    if not arrived.wait(MEET_WAIT):
        with _meeting:
            if not arrived.is_set():
                _waiting.clear()
                raise ValueError(f"no other call of tally meet ran beside {name} within {MEET_WAIT:.0f} s")
    return theirs[0]
