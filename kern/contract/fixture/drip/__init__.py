"""The streaming fixture in Python: drip, whose steps outlast the core's step wait."""

import time

from kern import component

drip = component("drip")


@drip.command("drip talk")
def talk(args, inputs, say):
    count = int(args[0])
    for i in range(1, count + 1):
        say(f"tick {i}")
        time.sleep(0.25)
    return f"said {count} lines"


@drip.command("drip quiet")
def quiet(args, inputs, say):
    time.sleep(float(args[0]))
    return "slept"
