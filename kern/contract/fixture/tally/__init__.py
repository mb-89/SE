"""The contract suite's fixture component in Python: tally, as contract/fixture.go answers it in Go."""

from kern import component

tally = component("tally")


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
