# Overhaul: is the design still right?

Reader: whoever changes how an overhaul runs, and the box judging one.

The retro ([retro.md](retro.md)) checks whether the rules held over its
window. The overhaul asks the bigger question, rarely: is the design still
right? Are we drifting from the design principles
([principles.md](principles.md)), and how does SE compare with current state of
the art and with what others build? It is mostly judgment, and it looks at the
whole system, not a window.

## The rules

- **An overhaul is an issue** labelled `se` and `se-overhaul`, created by
  `se overhaul new` (through the same code as `se issue new`), which fires the
  routine, as fan-out does, so a box takes it at once. Like a retro, it never
  waits for the owner, whoever started it. `--unattended` records that no
  person started it; the cadence starts overhauls this way. The issue's body
  records which it is, `<!-- se:overhaul attended -->` or
  `<!-- se:overhaul unattended -->`.
- **The cadence:** every `OverhaulCadence` (in
  `src/internal/issues/cadence.go`) closed retros since the last closed
  overhaul (with none closed yet, the whole history), `se issue pull --take`
  starts an unattended overhaul and takes it first, ahead of a due retro and
  all other work. It is the same mechanism as the retro cadence, one constant.
  An open `se-overhaul` issue, attended or not, means no second one is
  started; one started in a race with a lower one closes itself as its
  duplicate, as a retro does. `--take N` skips the cadence; the plain `se issue pull` reports the
  count beside the retro's.
- **The box** takes an overhaul like any issue (`se issue pull --take` says it
  is an overhaul) and follows the overhaul skill,
  [src/plugin/skills/overhaul/SKILL.md](../src/plugin/skills/overhaul/SKILL.md),
  instead of landing a branch.
- **The mechanical half,** `se overhaul read N`, writes a report draft beside
  the checkout (`../overhaul-N.md`). It holds:
  - every principle of [principles.md](principles.md), with what checks it,
    and whether the retro or the battery checks it mechanically;
  - the retro's last `OverhaulCadence` runs, from their reports' blocks: each metric, the
    broken rule checks by kind, how many findings became issues and how many
    of those closed, how many the next retro found recurred anyway, and the
    finding classes more than one of them named;
  - the previous overhaul's findings and the state of their issues.
- **The judgment half (the box):** every principle one by one, the outside
  world, the consistency of the whole system, the principles themselves, the
  retro's effectiveness, speed, what to mechanize and what to remove, the
  findings and what went well. What each part asks and the fields it writes
  into the draft's block are the overhaul skill's (its step 3).
- **Minting:** the same rule as the retro's (the owner's rule in
  [retro.md](retro.md)). Every finding becomes an issue through the same code
  as `se issue new`. A controversial one is an issue for a person, labelled
  `se-person` and assigned to the owner; the rest go to the normal queue. A
  change to a principle is always controversial: `se overhaul file` makes it
  so. `se overhaul file` creates the issues at once, posts the report as the
  closing comment and closes the overhaul: it never waits. (A report posted
  for the owner before overhauls stopped waiting is handed back by
  `se overhaul read` and filed as it stands.) It deletes the claim `issue-N`,
  as a retro does.
- **`se overhaul file` refuses**, writing nothing, a judgment that is not
  complete: a principle without a verdict, or a verdict without `strays` and
  `how`; an empty `looked_at` part ("nothing to change" is an answer); a
  finding without a title, a body, a known area, a principle on the list, a
  place, or `strays`; an outside finding without a source; a controversial
  one without a `why`; nothing that went well.
- **The report stays on the overhaul issue** as its closing comment, opening
  with `<!-- se:overhaul-report -->`, with a machine-readable block under
  `<!-- se:overhaul-yaml -->`: the principles, the retros' numbers, the
  verdicts, what was looked at, the findings with the issues they became, and
  what went well. The next overhaul reads it first and compares.

## The commands

<!-- se:manifest usage overhaul -->
```
se overhaul file N [--draft FILE] [--json] [--repo OWNER/NAME]
se overhaul new [--unattended] [--json] [--repo OWNER/NAME]
se overhaul read N [--out FILE] [--json] [--repo OWNER/NAME]
```
<!-- /se:manifest -->

All three are offered in a session, as `/se overhaul <word>`. They read and
write GitHub through `gh api`, as the issue commands do
([issues.md](issues.md)), in `src/internal/issues`.
