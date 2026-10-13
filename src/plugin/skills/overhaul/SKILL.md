---
name: overhaul
description: Start an SE overhaul, or, as the box that took one, judge SE against every principle and the outside world and file its report. The work skill hands an issue labelled se-overhaul to it.
---

# Overhaul: is the design still right?

Reader: the agent starting an overhaul with a person, or the box that took one.

The rules are [spec/overhaul.md](../../../../spec/overhaul.md). `se` is
`./src/plugin/bin/se`, called exactly as `./src/plugin/bin/se overhaul …`,
one command per call.

## Starting one, with a person

Run `./src/plugin/bin/se overhaul new` and tell the person the issue it
created. A box takes it from there and stops with its report for them.

## The box that took overhaul N

1. `./src/plugin/bin/se overhaul read <n>`. It writes the draft to
   `../overhaul-<n>.md`. If it says it wrote the report already posted on the
   issue, the owner has decided: read their comments on the issue, apply what
   they moved between controversial and not to `findings` in the draft's
   block, and go to 4.
2. Read the draft's facts: the principles, the retro's last five runs, the
   previous overhaul's findings. Then read SE itself: `spec/`, the README,
   CLAUDE.md, the skills, `se help`, and the code under `src/`.
3. Judge, and write it into the draft's block (the YAML under
   `<!-- se:overhaul-yaml -->`); leave the facts as they are.
   - `verdicts`: one per principle, `principle`, `strays` (`none`,
     `slightly`, `far`) and `how`. For a mechanical one, read the retros'
     rule checks and metrics; for the rest, read the code and spec against
     the principle's text.
   - `looked_at`: `outside` (search the web for current practice and tools in
     agent orchestration, issue-driven work, testing with fakes and
     contracts, plugin and hook design, and for comparable systems; cite
     them), `consistency` (do the README, spec, help, skills and CLAUDE.md
     describe what the code does; does every part fit the parts that rely on
     it), `principles` (is one missing, obsolete or in conflict), `retro`
     (did its metrics move; did findings recur anyway).
   - `findings`: each a `title` (the fix, as an issue title), a `body` (what
     strays, with files and issue numbers, and the fix), its `area`
     (`principle`, `outside`, `consistency`, `principles`, `retro`), the
     `principle` it names (0 only for a missing one), the `place`, how far
     it `strays` (`slightly`, `far`), `sources` for an outside idea (one
     becomes a finding only with a concrete place in SE it would change),
     and `controversial` with its `why` when it trades one metric against
     another, you are not sure, or it recurred after an earlier fix. A
     change to a principle is always controversial.
   - `went_well`: what holds and should stay.
4. `./src/plugin/bin/se overhaul file <n>`. If it refuses, fix what it names
   and run it again. It either posts the report and gives the overhaul to the
   owner, or creates the issues and closes it. Either way, end: there is no
   PR to land.
