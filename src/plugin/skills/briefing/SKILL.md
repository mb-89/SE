---
name: briefing
description: Brief the person on where SE stands, what waits on them first, then what is in flight, what happened and what is next, and ask what they want to work on. It presents; it does not act.
---

# Briefing: where SE stands

Reader: the agent briefing a person.

Every fact comes from one command; you present them, and you act on none.
`se` is `./src/plugin/bin/se` in the SE checkout; if it is missing, build it
with `go build -ldflags "-X main.commit=$(git rev-parse HEAD)" -o src/plugin/bin/se ./src/cmd/se`.

1. Run `./src/plugin/bin/se briefing` from the checkout's root. Pass the
   person's window if they gave one: `--since <time>` (a date, an RFC 3339
   time, or an age such as `36h` or `3d`) or `--last <n>`.
2. Read the documents its last section links, `spec/principles.md`,
   `spec/issues.md` and `CLAUDE.md`, for your own context. Do not summarize
   them to the person unless asked.
3. Present the briefing to the person, in this order:
   1. **What waits on you**, first and prominent: each item with its reason,
      its link and how many issues it holds up. If nothing waits, say so in
      one line.
   2. **In flight:** the claimed issues and their PRs with their state, and
      what fleet check reports.
   3. **What happened:** the closed issues, each with its `done` line, then
      the last retro and its headline findings.
   4. **Next:** what `se issue pull` would take, and the counts.
   Keep each item to its facts; add no judgment of your own.
4. Ask the person what they want to discuss. This session is for design;
   what comes out of it that is clear becomes an `se` issue for the fleet
   (`se issue new`), not work this session does ([principle 20](../../../../spec/principles.md)).

Change nothing: no issue, label, branch, comment or PR. If the person asks
for something, that is a new request, handled after the briefing.
