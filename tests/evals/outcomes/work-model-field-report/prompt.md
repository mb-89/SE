---
schema_version: "1.0"
name: work-model-field-report
description: A worker asked for its pull request description writes a field report whose Not delivered part names the unfinished requirement.
tags: [work-model]
runs: 3
max_turns: 20
timeout_seconds: 600
allowed_tools: [Skill, Read]
expected_outcome: The reply is a field report between its markers, and its Not delivered part names the CSV export.
---

You are the worker on work issue 31 of `example/app`, on the branch `feat/report-formats-20261114`.
Your work is done for this session. Reply with your pull request description, the whole text,
ready to paste; there is no shell and no GitHub tool in this run, so do not try to push.

The work issue, as the GitHub tools returned it:

```json
{"number": 31, "title": "feat/report-formats-20261114", "state": "open",
 "labels": ["work", "in-progress"],
 "body": "## Requirements\n\n1. **JSON output.** `app report --json` prints the report as JSON.\n2. **Since filter.** `app report --since <date>` drops entries before the date.\n3. **CSV export.** `app report --csv <file>` writes the report as CSV.\n\n## Acceptance\n\n- [ ] Each option has a test.\n- [ ] The test suite passes."}
```

Your tickets, as `work_tickets.py status` printed them:

```text
done  r1-json-output   evidence: tests/test_report.py::test_json passed; commit 1a2b3c4
done  r2-since-filter  evidence: tests/test_report.py::test_since passed; commit 5d6e7f8
held  r3-csv-export    not started: the CSV library the issue implies is not a dependency, and
                       adding one is not this issue's to decide
done  delivery         suite: 212 passed in 41 s
```
