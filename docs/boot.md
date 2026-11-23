# Start and update

Reader: the person who starts SE and decides when to update, and whoever changes SE's start. This
page owns SE's start report, the boot that lists what is behind, and the one update the report
names (work issue SE#1719, the person's decisions of 23 Nov 2026). Everything else of the start is
README [Start and refresh](../README.md#start-and-refresh).

## The start report

SE's first message is its start report, the same on every start and generated from what loaded:

```text
SE 12.0.1 started
[3 skills](<docs>#docs-skills)
[70 rules](<docs>#docs-rules)
[4 sub-agents](<docs>#docs-sub-agents)
[Documentation](<docs>)

| component | loaded | newest |
|---|---|---|
| SE | 12.0.1 | 13.0.0 |
| obs | 10.3.2 | 10.3.2 |

To update: /se:update
```

- **Its shape is a template**, `templates/boot-report.md`: a snippet, a message of several lines
  that the template engine writes and checks like any other filled template (README
  [Templates](../README.md#templates)). `scripts/se_start.py` only fills its fields.
- **The counts** are what the plugin's layout loads, as the documentation's pages list them:
  [Skills](skills.md), guidance notes aside; [Rules](rules.md), the rule book's and every guidance
  note; [Sub-agents](sub-agents.md), every agent but SE. `se_plugin.py build` writes the three pages
  from the layout it builds.
- **The table** holds SE first, then every component of the project's tree that `se.lock` holds,
  nested ones included. `loaded` is the version in use; `newest` the newest release the last update
  check read, `unknown` before one has, `local` for a local path.

The last line is one of three. `To update: /se:update` where a newer release than one loaded is
known; `Everything is current.` where none is; `Newest versions not read yet; the next start shows
them.` where a newest version is unknown. No path, no command line and no per-component line
appears in the report.

- **What the session alone acts on** comes below the report in the start's hand-over, under `For
  the session, not part of the report:`: the bootstrap's notes, kern's state (no pid), a stale
  plugin, a check that failed, the project's component listing, a skill the session lacks, a retro
  or overhaul due and the fleet's findings.
- **The person sees the report alone**, a stop of the start (`SE cannot start`) above it.

## The boot

`se_start.py boot` gets a checkout up to speed, like `npm outdated` in one command, and lists what
is behind. It runs its steps in order, each decided from versions alone, and reports once:

1. **The checkout current.** It fetches origin and brings the checkout to the newest tip of its
   branch: `origin/<branch>`, and on a branch other than the integration branch
   `origin/<integration branch>` too, by a fast-forward where it can, else by a merge.
   - A detached HEAD moves to the integration branch's tip where that tip leads on from it; else
     it stays, named.
   - It never discards local work: a merge over local changes is not started, and one that
     conflicts is aborted. Either, or a fetch that fails, is one `Checkout:` line, and the boot
     stops there with exit code 1.
2. **The dependencies listed.** SE itself, with its installed and newest version, and every pin of
   the project's component tree, nested ones included, as `se_modules.py breaking` reads them: one
   row each, `<holder> pins <name> <pin>, locked <version>, newest <version>`, and its verdict.
   - The verdict: `current`, or `the upgrade takes <version>`, the newest release the pin admits;
     a local path is never touched.
   - A release beyond a pin is listed as `breaking` or `newer`, with what moving the pin needs.
     The boot never takes it; the update does.
3. **The upgrade**, with `--upgrade` only: SE and every lock moved within the pins, as `refresh`
   moves them, trial start included; a development checkout stays. Commit `se.lock`.
4. **The report**: the rows, then `Moved: <n> items` after an upgrade, else the items there are to
   take, and `Left: <n> releases beyond a pin` where there are.

It exits 0 where every step ran, and 1 where the boot stopped, a listing failed or a move failed,
each named in its line.

## The update

`/se:update`, the skill `update`, is the one command that takes everything: it runs
`se_start.py update` and then follows what that prints. Each step is decided from versions alone:

1. **The checkout current**, as the boot's first step; a stop ends the update there.
2. **SE to its newest release**, across a major too, as `refresh` moves it, trial start included;
   where the project pins se (`[components.se]`), that pin moves with it. A development checkout
   stays.
3. **Every pin the newest releases need.** Each of the project's own pins whose newest release lies
   beyond it moves to that release: a range to `^<newest>` in `se.toml`, a go pin's require in
   its `go.mod`. A component's own pin is a ticket for its repository; a commit pin is named with
   the command that moves it.
4. **Every lock** to the newest release its pin admits; commit `se.toml`, `se.lock` and `go.mod`.
5. **The upgrade guide's steps between the versions**: the sections of `docs/upgrading.md` from the
   version left to the version taken, SE's from the new SE's guide, each component's from its own
   guide or else SE's, in order. The skill follows each, every step and then its check.

It exits 0 where every step ran, and 1 where it stopped or a move failed. Run again, it moves
nothing and prints `the update is done`. In a cloud session the [se agent](../src/agents/se.md#tools)
runs it as its first action after the report; on a local machine on the person's yes.
