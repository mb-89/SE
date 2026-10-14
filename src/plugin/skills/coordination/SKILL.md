---
name: coordination
description: When se issue pull --take takes nothing, check what is broken in the fleet and fix it before ending. The work skill hands over to it.
---

# Coordination: nothing to take, so check what is broken

Reader: the agent of a box that took nothing.

The rules are [spec/coordination.md](../../../../spec/coordination.md). `se` is
`./src/plugin/bin/se`, called exactly as `./src/plugin/bin/se …`, one command per call.
You are on `origin/main`, as the work skill left you.

1. `./src/plugin/bin/se fleet check`. If it says `healthy`, end the session: say
   nothing anywhere.
2. `./src/plugin/bin/se fleet fix`. It applies every remedy that needs no
   checkout; its lines `did: left to this box: …` are the takeovers.
3. For the first takeover it names, run its remedy:
   `./src/plugin/bin/se issue pull --take <n>`.
   - If it says the issue went to a person, or another box took it over, or
     nothing about it is stuck, go to the next takeover.
   - If it took the issue over, you are on its branch `issue-<n>`: follow the
     work skill's steps 3 to 5 for it (merge `origin/main` in, never rebase;
     make it green; land it with `./src/plugin/bin/se issue land`; subscribe to
     the PR and fix a red CI run). The takeover's comment on the issue is the
     record. One takeover per box: when it is landed, end.
4. With no takeover left, end.
