# Design principles

Reader: whoever designs, reviews or judges a change to SE, and the retro and the overhaul.

The list SE's design is measured against. The retro (#40) checks the
principles it can check mechanically; the overhaul judges every one. Each
principle is one sentence and one paragraph, and names what checks it. The
second part, [How code is written](#how-code-is-written), names the general
principles of code once.

1. **Mechanize first.**
   Every step that can be a deterministic, tested `se` command is one; agents
   keep only judgment. A box does the issue's work and fixes a red CI run;
   everything around that is a command with tests.
   Checked by: retro, mechanically (`by-hand` answers, scripts in `src/scripts/`).

2. **Single point of truth.**
   Every fact lives in one place, and everything else is derived from it: the
   command registry, the landing questions, this list. A fact written twice
   drifts.
   Checked by: `se overhaul read` (duplicates, near-duplicates); overhaul, by
   judgment.

3. **Locality.**
   One change happens in one place, and the system picks it up everywhere by
   registration, never by hand-kept lists; understanding a change means
   reading one place.
   Checked by: `se overhaul read` (files touched per change); overhaul, by
   judgment.

4. **Modularity.**
   Behaviour lives in modules that register with a small core, the index
   (v5's index and modules, adopted). An agent changing a module needs the
   module contract, not the whole engine.
   Checked by: overhaul, by judgment.

5. **Thin adapters.**
   The Go program owns the logic. The plugin, the CLI and the UI are thin,
   and the UI is generated from the registry.
   Checked by: overhaul, by judgment.

6. **One I/O module per outside thing.**
   Processes, disk, the clock, the network and GitHub are each reached
   through exactly one I/O module, and nothing reaches the outside any other
   way. A run has three phases: it reads its inputs, computes, then writes
   its outputs. It reads everything it needs once, at the start, batched
   (one list or one server-side query, not one call per item) and in
   parallel where reads are independent, into one snapshot. The computing in
   between is pure and works on that snapshot alone. A run never asks the
   outside world again for what it already has: that is slow, and inputs
   read at different times disagree. No process does what a library call
   can do: the proc I/O module starts only programs that are themselves the
   work (`go`, the battery's linters, `git` where Go has no library for it),
   one listed value, `proc.Programs`; GitHub is reached through its own
   module's HTTP client, never `gh`. An I/O module is a door: it declares
   the resource it guards and what going around it looks like, and nothing
   goes around it, neither code nor an agent; an agent reaches GitHub only
   through `se`. A box's run has the same three phases: its take reads and
   claims, its land (or supersede, or close) writes once, and in between it
   works locally (commits, fetches and merges main) and is silent on GitHub.
   Checked by: the battery (the `io-module` and `programs` rules of
   `se rules`); overhaul, by judgment (`looked_at.speed`).

7. **Fakes that behave, held to contracts.**
   Every I/O module has a fake, and one contract suite runs against both the
   fake and the real thing; a fake without its suite is refused.
   Checked by: the battery (the `fake-contract` rule of `se rules`).

8. **Fast tests.**
   Test a behaviour once, at the outermost interface (the `se` command), on
   fakes. Real I/O modules appear only in their contract tests. No wall
   clock, no sleeping, tests run in parallel, fixtures are built once, and
   test code stays at or under code size.
   Checked by: the battery (the `fast-test` rule: parallel tests, no wall
   clock); `se overhaul read` (the test ratio); overhaul, by judgment.

9. **Performance is measured, and a person never waits blind.**
   The battery, every test, each `se` command and each plugin hook record
   their duration, and soft budgets in one file
   ([spec/budgets.yaml](budgets.yaml)) report what grows (#50). One hard
   rule: anything a person waits on gives feedback within 1 second and never
   blocks. What can run in parallel does. A person never waits on the outside
   world: what a person triggers, typed or pressed, is answered from the
   snapshot the daemon holds, which the I/O modules refresh in the
   background; only a command that must write (a claim, a land) goes out at
   once. Every command declares its class, interactive or batch, and each
   interactive one keeps a hard time and request budget, run against fakes
   that delay each request and process start as the outside world does.
   Checked by: the battery (each interactive command against its budgets,
   reported in its profile) and the bridgehead; overhaul, by judgment
   (`looked_at.speed`).

10. **Lint and style checks are part of the battery.**
    Standard linters and formatters, plus SE's own rules written as checks;
    nothing reaches main past a failing one. A retro finding whose home is
    "a check" lands here.
    Checked by: the battery itself.

11. **GitHub is the only shared state.**
    Nothing private, nothing that dies with a box: what a later box or retro
    needs is on GitHub.
    Checked by: retro.

12. **One work system.**
    Issues with native links, created only through `se issue new`; a box acts
    on its issue's text, not on messages. An issue is work: code or prose
    that must change. It is never a way to report, ask or tell: what a run
    finds that changes nothing is said in its own output (a PR, a landing
    answer, a report), not in a new issue.
    Checked by: retro, mechanically (rule checks).

13. **Every session starts at main.**
    Both the code being worked on and the SE that runs the session start at
    main.
    Checked by: overhaul, by judgment.

14. **Fail open for advice, closed for enforcement.**
    Logging and help never block; a rule that guards something refuses when
    it cannot decide.
    Checked by: overhaul, by judgment.

15. **Agents decide, persons review.**
    Better to ask for forgiveness than for permission. An agent that can make
    a decision makes it, names it, and goes on; a person looks at the named
    decisions afterwards, in the review and the retro, and says where one was
    wrong. Needing a decision is never a reason to stop. Neither is being
    unsure, a merge conflict, a trade-off between two metrics, or a fix that
    failed once. If you can do something yourself, you do it yourself, and a
    decision you can make is yours. This is the one place the rule lives; the
    agents point here.
    A person is needed only for what only a person can do, and an issue for
    a person is the last resort, for one of two kinds:
    - **access**: a setting, an account, a secret, a permission or a payment
      only the owner has (a repository ruleset, say);
    - **principle**: a change to a design principle.
    `se issue new --person` refuses anything else (`--why access|principle`,
    and `--what`, a sentence saying what only the person can do), and so does
    every other path that mints one. Every run ends, and such an issue is
    never how: a box lands a PR or a supersede and opens no issue
    (`se issue new` refuses in one), its open points in its landing answers
    (`open`), which the retro reads; a retro or an overhaul closes once its
    issues exist. What needs the person's answer is blocked by their issue,
    and nothing else is. Every landing names its decisions (`decisions` in
    [landing.yaml](landing.yaml)). A review, a retro or an overhaul exists to
    file issues: they are its output, filed through its own command in one
    go at its end, as one manifest of finals (`se-final`, the findings its
    sub-issues), or for a person where only a person can do it. Finals do
    not count toward the retro's cadence, so retros do not feed themselves.
    Checked by: retro, mechanically (issues for a person per closed issue,
    against a soft budget, and the window's named decisions listed for the
    owner); overhaul, by judgment.

16. **Blameless.**
    Fix what produced a bad outcome (a rule, a tool, a prompt), never just the
    outcome.
    Checked by: retro and overhaul, by design.

17. **Consistency.**
    The system agrees with itself: every part still fits the parts that rely
    on it, and nothing describes behaviour other than what the code does.
    Checked by: the battery (mechanical checks, generated manifests); the
    reviewer (in its scope: does anything in or around the change now
    disagree?); the retro (what became inconsistent in its window); the
    overhaul (the whole system).

18. **Talk only about what you own.**
    Every element either owns content and talks only about itself, or is a
    manifest: a generated map that points at owners and says nothing about
    their content. A hand-written element that describes something it does
    not own (the README listing what commands do, a skill restating a spec
    rule, CLAUDE.md copying a process) is a defect. It points instead, or
    becomes a generated manifest (`se help manifest`).
    Checked by: the battery (manifests regenerate identically; every `se`
    command, path and link prose names exists); the reviewer, the retro and
    the overhaul (hand-written restatements are findings).

19. **Write for your reader.**
    Before writing prose, name who reads it and what they need from it. Then:
    - **bottom line up front:** the first lines say what the reader most needs;
    - **progressive disclosure:** simple first, detail only further down and
      only as far as this reader needs it;
    - **point, don't explain:** where someone else explains it in more
      detail, reference them (principle 18).

    What a reader doesn't need leaves, even if it is true and owned. Each
    prose file names its readers in one line at the top, `Reader: …`, under
    its title (for example: README, a person meeting SE for the first time;
    CLAUDE.md, an agent working in this repo; a skill, the agent running it;
    `spec/`, whoever changes that part).
    Checked by: the battery (the line is there); the reviewer, the retro and
    the overhaul (prose that serves no named reader is a finding).

20. **The fleet works; sessions discuss.**
    An interactive session with a person is for design: deciding what SE
    should be and how. Work that is clear becomes an `se` issue, and the
    cloud fleet does it; the session does not do it itself.
    Checked by: retro and overhaul, by judgment.

21. **The rule of five.**
    A surface a person sees, the root, `spec/` and `src/`, holds at most five
    visible files and at most five visible folders; dot files and dot folders
    do not count. A person looking at SE sees what is there for them, not the
    tools SE is built with. The limit, the surfaces and the allowlist of
    today's violations, which only shrinks, live in one configuration.
    Checked by: the battery (the `rule-of-five` rule of `se rules`, configured
    in `src/internal/rules/five.yaml`).

22. **Steer before, check at the push.**
    What an agent gets is settled before it starts: the take hands over the
    skills its issue names, in full, and the session starts with these
    principles. What must hold is checked when the work is pushed, by the
    battery and the landing. Nothing steers the agent in between: no canary,
    no tool refusals during the work.
    Checked by: the take (`se issue pull --take` hands the skills over, the
    session's log records them); the battery and `se issue land` (the push).

## How code is written

The general principles of code, named once, one line each. The overhaul
applies them to all of SE and the reviewer to its change; `se overhaul read`
lists the facts a command can find for them. A finding names the principle or
smell, the places, and the shape the code should take (for example "one run
engine; retro and overhaul become strategies").

- **Once and only once (DRY)**, with principle 2, held against the **rule of
  three**: generalize at the third repetition, not the second; a little copying
  is better than a little dependency. Checked by: `se overhaul read`
  (duplicates, near-duplicates); overhaul and reviewer, by judgment.
- **KISS and YAGNI:** no speculative generality, nothing built for a second
  user that does not exist. Checked by: `se overhaul read` (one-user
  abstractions, unused surfaces); overhaul and reviewer, by judgment.
- **Single responsibility, separation of concerns, command–query separation.**
  Checked by: `se overhaul read` (longest functions and files); overhaul and
  reviewer, by judgment.
- **Open for extension by registration** (principle 3), **dependency
  inversion** (I/O behind interfaces, principle 6), **interface segregation**
  (the bigger the interface, the weaker the abstraction). Checked by: the
  battery (the io-module rule); overhaul and reviewer, by judgment.
- **Functional core, imperative shell:** principle 6's three phases. Checked
  by: overhaul and reviewer, by judgment.
- **Fail fast** at the edges. Checked by: overhaul and reviewer, by judgment.
- **Clear is better than clever.** Checked by: overhaul and reviewer, by
  judgment.
- **Reuse before you write:** before building a check, a skill or an agent,
  look for one that exists (Go's own tools, golangci-lint's linters, published
  Claude Code plugins) and integrate it rather than rewrite it. Checked by:
  overhaul (`looked_at.outside`) and reviewer, by judgment.
- **Patterns, where they fit:** strategy (one algorithm, its variants as
  pluggable strategies or configuration), table-driven code in place of switch
  chains, template method (one flow with hooks), registry, adapter (thin,
  principle 5), command (requests as data, the index's actions) and state
  machine (lifecycles such as an issue's). Checked by: `se overhaul read`
  (switches on a kind); overhaul and reviewer, by judgment.
- **Smells to find:** shotgun surgery (one change in many files: fixing one
  thing in five places), divergent change, duplicated and near-duplicated
  code, long function, large module, long parameter list, data clumps,
  primitive obsession, feature envy, switch on a kind. Checked by:
  `se overhaul read` (files touched per change, duplicates, longest functions,
  files and parameter lists, sizes, switches on a kind); overhaul and
  reviewer, by judgment.
- **The less code, the less to maintain:** code nothing reaches, code for a
  state that no longer occurs, and code that restates what another place
  holds is removed. Checked by: the battery (`deadcode -test` reports
  nothing); `se overhaul read` (the pruning facts); overhaul, by judgment
  (`looked_at.removal`).
