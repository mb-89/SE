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
  routine, as fan-out does, so a box takes it at once. Like a retro, it is
  attended by default: its box stops for the owner with the report.
  `--unattended` never stops; the cadence starts overhauls this way. The
  issue's body records which it is, `<!-- se:overhaul attended -->` or
  `<!-- se:overhaul unattended -->`.
- **The cadence:** every `OverhaulCadence` (5, in
  `src/internal/issues/cadence.go`) closed retros since the last closed
  overhaul (with none closed yet, the whole history), `se issue pull --take`
  starts an unattended overhaul and takes it first, ahead of a due retro and
  all other work. It is the same mechanism as the retro cadence, one constant.
  An open `se-overhaul` issue, attended or not, means no second one is
  started. `--take N` skips the cadence; the plain `se issue pull` reports the
  count beside the retro's.
- **The box** takes an overhaul like any issue (`se issue pull --take` says it
  is an overhaul) and follows the overhaul skill,
  [src/plugin/skills/overhaul/SKILL.md](../src/plugin/skills/overhaul/SKILL.md),
  instead of landing a branch.
- **The mechanical half,** `se overhaul read N`, writes a report draft beside
  the checkout (`../overhaul-N.md`). It holds:
  - every principle of [principles.md](principles.md), with what checks it,
    and whether the retro or the battery checks it mechanically;
  - the retro's last five runs, from their reports' blocks: each metric, the
    broken rule checks by kind, how many findings became issues and how many
    of those closed, how many the next retro found recurred anyway, and the
    finding classes more than one of them named;
  - the previous overhaul's findings and the state of their issues.
- **What the box checks, and writes into the draft's block:**
  - **Every principle, one by one** (`verdicts`: each a `principle`, how far
    SE `strays`, `none`, `slightly` or `far`, and `how`): the mechanically
    checkable ones through the latest retros' rule checks and metrics; the
    rest by reading the code and spec against the principle's text.
  - **The outside world** (`looked_at.outside`): current practice and tools
    relevant to SE's parts (agent orchestration, issue-driven work, testing
    with fakes and contracts, plugin and hook design), and what comparable
    systems do. Sources are cited, and an outside idea becomes a finding only
    with a concrete place in SE it would change.
  - **Consistency across the whole system** (`looked_at.consistency`;
    #83): do the README, the spec, the help, the skills and
    CLAUDE.md still describe what the code does, and does every part still
    fit the parts that rely on it?
  - **The principles themselves** (`looked_at.principles`): is one missing,
    obsolete or in conflict with another?
  - **The retro's effectiveness over its last five runs**
    (`looked_at.retro`): did the metrics move, and did findings recur anyway?
  - **Findings** (`findings`): each names the principle (`principle`; 0 only
    for a missing one), the place (`place`) and how far it strays (`strays`,
    `slightly` or `far`), with a `title`, a `body`, the `area` that found it
    (`principle`, `outside`, `consistency`, `principles` for a change to a
    principle, or `retro`), the `sources` an outside one cites, and
    `controversial` with its `why`.
  - **What went well** (`went_well`).
- **Minting:** the same rule as the retro's (the owner's rule in
  [retro.md](retro.md)). Every finding becomes an issue through the same code
  as `se issue new`. A controversial one is created with `se-person`,
  assigned to the owner; the rest go to the normal queue. A change to a
  principle is always controversial: `se overhaul file` makes it so. Attended,
  the report is posted first and the issue goes to the owner (`se-person`),
  who may move findings between the two kinds in a comment, then runs
  `se issue resume`; the next box takes it again, `se overhaul read` hands it
  the posted report, it applies what the owner decided, and `se overhaul file`
  creates the issues and closes the overhaul. Unattended, `se overhaul file`
  creates them at once and closes it. Either way it deletes the claim
  `issue-N`, as a retro does.
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

    se overhaul new [--unattended] [--json] [--repo OWNER/NAME]
    se overhaul read N [--out FILE] [--json] [--repo OWNER/NAME]
    se overhaul file N [--draft FILE] [--json] [--repo OWNER/NAME]

All three are offered in a session, as `/se overhaul <word>`. They read and
write GitHub through `gh api`, as the issue commands do
([issues.md](issues.md)), in `src/internal/issues`.
