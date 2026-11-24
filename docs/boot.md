# Start and update

Reader: the person who starts SE and decides when to update, and whoever changes SE's start. This
page owns SE's start report, the boot that lists what is behind, and the one update the report
names (work issue SE#1719, the person's decisions of 23 Nov 2026). Everything else of the start is
[Start and refresh](start.md#start-and-refresh).

## The start report

SE's first message is its start report, the same on every start and generated from what loaded:

```text
SE 12.0.1 started
[3 skills](https://example.com/se/#docs-skills)
[70 rules](https://example.com/se/#docs-rules)
[4 sub-agents](https://example.com/se/#docs-sub-agents)
[Documentation](https://example.com/se/)

| component | loaded | newest |
|---|---|---|
| SE | 12.0.1 | 13.0.0 |
| kern | 2.1.0 | 2.2.0 |
| obs | 10.3.2 | 10.3.2 |
| obs-html | 0.5.2 | 0.5.2 |

To update: /se:update. The next SE release brings kern 2.2.0.
```

- **Its shape is a template**, `templates/boot-report.md`: a snippet, a message of several lines
  that the template engine writes and checks like any other filled template ([Templates](templating.md#templates)). `scripts/se_start.py` only fills its fields.
- **The counts** are what the plugin's layout loads, as the documentation's pages list them:
  [Skills](skills.md), guidance notes aside; [Rules](rules.md), the rule book's and every guidance
  note; [Sub-agents](sub-agents.md), every agent but SE. `se_plugin.py build` writes the three pages
  from the layout it builds.
- **The table** holds SE first, then SE's [required components](#required-components) as they
  answered, then every component of the project's tree that its `se.lock` holds, nested ones
  included, but one a required row already shows.
  - `loaded` is the version in use: for a required component the version that answered at this
    start, never the locked one, and `none` where it did not load; for the project's own, its lock.
  - `newest` is the newest release the last update check read, `unknown` before one has, `local`
    for a local path.
  - Where the project locks a required component at another version than the one SE loaded, the
    session is told in one line.

The last line is computed from the table's rows alone, so it never contradicts them
(`update_line` in `scripts/se_start.py`). A row is behind where its newest release is newer than
its loaded version, or where it loaded `none` from the project's lock; `local`, `unknown` and a
core switched `off` never are. In order, the first that holds:

- `Not loaded: <names>. SE cannot start.` where a required row did not load, as the stop above
  the report says.
- Where rows are behind: `To update: /se:update` for a row SE does not lock, SE's own or the
  project's. For a required row, which SE locks so only the next SE release moves it, `The next
  SE release brings kern 2.2.0 and obs 10.4.0.`, each such row with its newest release. Where
  both hold, the line says both, the update first, as the example above.
- `Newest versions not read yet; the next start shows them.` where a row's newest is `unknown`.
- `Everything is current.` where every row is current.

The project's own lock of a required component has no row, so it changes no last line; where it
differs from the version SE loaded, the session is told in one line. No path, no command line and
no per-component line appears in the report.

- **What the session alone acts on** comes below the report in the start's hand-over, under `For
  the session, not part of the report:`: the bootstrap's notes, kern's state (no pid), a stale
  plugin, a check that failed, the project's component listing, a skill the session lacks, a retro
  or overhaul due and the fleet's findings.
- **The person sees the report alone**, a stop of the start (`SE cannot start`) above it.

## Required components

SE cannot work without kern, obs and obs-html (the person, 24 Nov 2026), so they are SE's required
components: every component SE's own `se.toml` declares and does not mark `optional`, each locked
in SE's `se.lock`, apart from any project's tree.

- **Every start loads each from SE's root**, wherever the session starts: inside a project, in
  SE's own checkout, or in a folder that is no repository, as a cloud session's `/home/user`. The
  start hook does it, and `se_start.py status --greeting` by hand the same.
  - **SE's tree** is placed at its lock first, from what is placed, as
    [docs/components.md](components.md#required-and-optional-at-start) places a project's.
  - **kern** is installed at its pin and running: `bootstrap.sh` fetches or builds the binary,
    starts the core and hands it the session's start, for the project where it lies inside a git
    checkout, else for SE's root ([Kern](start.md#kern)).
    - A first fetch or build runs in the background, and the start waits for it up to
      `SE_KERN_WAIT` seconds, 45 by default.
    - The core answers `status`; its row is the kern version the running binary is built on.
  - **obs** answers by importing in its own environment, from its clone; its row is the version of
    the obs that imported.
  - **Every other** is a component obs installs (obs-html, its adapter): where obs has none or
    another version, `obs-components install <name> <version>` installs SE's locked one, and an
    adapter then runs its command with `--help`. Its row is the version obs has installed.
- **One that does not load stops the start**: one line each above the report, naming the component
  and the cause, `SE cannot start: the required component <name> did not load: <cause>`, and its row
  says `none`. A tree that cannot be placed is one line naming every required component.
- **A core switched off** on the machine (`SE_HOOK_CORE=off`, or `[hooks] core = "off"`) is the
  person's choice, no failure: kern's row says `off`, and the session is told.

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
   - Once SE moved, each core that stands for the project or SE's root restarts with the binary the
     start named and is handed the session's start, so no component answers with the code it
     loaded before. One line each; a core that does not come back fails the update.
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
