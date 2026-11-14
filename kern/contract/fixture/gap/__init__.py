"""The long local phase's fixture in Python: gap, whose second step works longer than a reply's
time on the bus before it asks its next GitHub step."""

import time

from kern import component

gap = component("gap")

WHERE = {"owner": "alice", "repo": "demo"}


@gap.command("gap run")
def run(args, inputs, say):
    seconds = float(args[0])

    def last(answers):
        return f"heard {answers[0]['tool']} after {seconds:g} s of work"

    def work(answers):
        say(f"heard {answers[0]['tool']}; working {seconds:g} s")
        time.sleep(seconds)
        say("asking list_issues")
        return gap.result(requests=[gap.ask("step", {
            "tool": "list_issues", "input": {**WHERE, "state": "OPEN", "perPage": 20}})], then=last)

    return gap.result(requests=[gap.ask("step", {
        "tool": "issue_read", "input": {**WHERE, "method": "get", "issue_number": 7}})], then=work)
