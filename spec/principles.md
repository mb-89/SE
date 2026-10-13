# Design principles

The list SE's design is measured against. The retro (#40) checks the
principles it can check mechanically; the overhaul judges the rest. Each
principle is one sentence and one paragraph, and names what checks it.

1. **Mechanize first.**
   Every step that can be a deterministic, tested `se` command is one; agents
   keep only judgment. A box does the issue's work and fixes a red CI run;
   everything around that is a command with tests.
   Checked by: retro, mechanically (`by-hand` answers, scripts in `src/scripts/`).

2. **Single point of truth.**
   Every fact lives in one place, and everything else is derived from it: the
   command registry, the landing questions, this list. A fact written twice
   drifts.
   Checked by: retro, mechanically (a fact written twice is a finding); overhaul, by judgment.

3. **Locality.**
   One change happens in one place, and the system picks it up everywhere by
   registration, never by hand-kept lists; understanding a change means
   reading one place.
   Checked by: retro, mechanically (files touched per issue, as a metric); overhaul, by judgment.

4. **Modularity.**
   Behaviour lives in modules that register with a small core, the index
   (v5's index and modules, adopted). An agent changing a module needs the
   module contract, not the whole engine.
   Checked by: overhaul, by judgment.

5. **Thin adapters.**
   The Go program owns the logic. The plugin, the CLI and the UI are thin,
   and the UI is generated from the registry.
   Checked by: retro, mechanically (logic in the plugin hooks); overhaul, by judgment.

6. **One I/O module per outside thing.**
   Processes, disk, the clock, the network and GitHub are each reached
   through exactly one I/O module, and nothing reaches the outside any other
   way.
   Checked by: the battery (a lint rule, #44's tree).

7. **Fakes that behave, held to contracts.**
   Every I/O module has a fake, and one contract suite runs against both the
   fake and the real thing; a fake without its suite is refused.
   Checked by: the battery (a lint rule).

8. **Fast tests.**
   Test a behaviour once, at the outermost interface (the `se` command), on
   fakes. Real I/O modules appear only in their contract tests. No wall
   clock, no sleeping, tests run in parallel, fixtures are built once, and
   test code stays at or under code size.
   Checked by: retro, mechanically (battery time and the test ratio as metrics).

9. **Performance is measured, and a person never waits blind.**
   The battery, every test, each `se` command and each plugin hook record
   their duration, and soft budgets in one file (`spec/budgets.yaml`) report
   what grows (#50). One hard rule: anything a person waits on gives feedback
   within 1 second and never blocks.
   Checked by: the battery and the bridgehead; retro, mechanically (trend).

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
    on its issue's text, not on messages.
    Checked by: retro, mechanically (rule checks).

13. **Every session starts at main.**
    Both the code being worked on and the SE that runs the session start at
    main.
    Checked by: retro, mechanically (commit drift reported by `/se status`).

14. **Fail open for advice, closed for enforcement.**
    Logging and help never block; a rule that guards something refuses when
    it cannot decide.
    Checked by: overhaul, by judgment.

15. **Persons decide, agents execute.**
    Anything controversial goes to a person; everything else flows without
    one.
    Checked by: retro, mechanically (`se-person` counts); overhaul, by judgment.

16. **Blameless.**
    Fix what produced a bad outcome (a rule, a tool, a prompt), never just the
    outcome.
    Checked by: retro and overhaul, by design.
