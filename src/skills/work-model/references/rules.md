# Rule book

Reader: whoever designs, reviews or judges a change to se or a project that uses it, and every
place that cites a rule.

Every rule lives here once, cited by its id. Other places name the id and link here; they never
restate the rule. `uv run python <se>/scripts/rule_book.py` checks the book, and the suite runs it.

## Ids

An id is `<area>-<number>` for a cross-cutting rule and `p-<project>-<number>` for a project's
rule, lowercase, the number with at least three digits: `gen-001`, `p-se-001`. A number may grow
past 999.

- **Areas:** `gen` (everything we do), `des` (software design), `tst` (testing and quality), `doc`
  (documentation and surfaces), `wrk` (work and fleet), `dec` (decisions), `pub` (publishing and
  security). No area starts with `p-`.
- **Projects:** each project has its own section, `p-` and its short name in lowercase letters and
  digits: `p-se`, `p-obs`, `p-go` for the Go line on `main`. Any number of projects can be added.
- **Never reused:** a retired rule keeps its id and says why it was retired.
- **Assigned by integrators:** a worker that needs a new rule proposes it with a placeholder name
  in its field report; the integrator gives it the next free number of its section.

## The shape of a rule

Each section is a `## <prefix>: <title>` heading, and each rule a `### <id> <name>` heading in its
section, followed by:

- one sentence stating the rule;
- **Why:** the reason;
- **Without it:** what we lose if the rule is dropped;
- **Prevents:** the kinds of defects it prevents, named as defect classes, not single incidents;
- **Implementations:** one item per language or project, each linking the check, script or skill
  passage that does it, or saying "by judgment";
- **Related:** the ids of related rules, or "none";
- **Retired:** only on a retired rule, the reason.

The check refuses a malformed id, a project id without `p-`, a duplicate or reused retired id, a
rule outside its section and a rule missing any of these fields; it lists, without failing, every
rule whose only implementation is "by judgment".
