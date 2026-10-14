# Index: the core and the module contract

Reader: an agent writing, moving or testing an SE module, and whoever changes the index core.

SE's behaviour lives in **modules** that register with a small **index**
([principle 4](principles.md)). The index moves values between **names** and
gathers what modules declare; it knows nothing else. A module declares its
inputs, outputs, config and commands by local name, reads one snapshot, and
commits its outputs. It never spells another module's name: one **wiring file**
binds the names. A module is tested alone, against a fake index.

This is the design; the code lands in the order of
[the migration](#the-migration). The core is `src/internal/index`, its fake
`src/internal/index/indextest`; their doc comments are the contract's detail. It adapts v5's model
([quackitect's `model.md` on `v5`](https://github.com/mb-89/quackitect/blob/v5/spec/design_output/model.md)): it keeps one writer per name, local ports with
outside wiring, one snapshot per run, built-in values, declarations that every
surface renders, and the fake index; it drops what SE does not need yet.

## The core

The core holds no business logic. It does six things:

| what the core does | how |
|---|---|
| keeps **names** | a name is a path of segments, such as `issues/open`. Each has exactly one writer (one module's output port), a type and a built-in value. A **family** carries a key segment, such as `session/<id>/events`, and is declared once; keys come and go inside it, so no name is added at runtime |
| keeps the **store** | name to value, with one revision for the whole store that every commit raises |
| takes a **write from the name's writer alone** | a commit names the module instance; the core refuses any name that instance does not write |
| hands out **snapshots** | a run reads all its inputs at one revision, never an old value beside a new one |
| **pushes changes** | after a commit, the core runs each module that reads a changed name, and tells each subscriber (an adapter waiting on a name). A commit that leaves a value unchanged pushes nothing |
| answers a **built-in value** where nothing is provided | a name no value stands in, or whose writer is not running, reads as the writer's declared built-in value, marked `not provided` |

It also **gathers declarations**: at start it collects every module's ports,
config and commands into one catalog, the collector. The catalog is a
manifest: it holds what modules declared and adds no text of its own.

**The index knows nothing about modules** ([principle 18](principles.md)). The
core never describes, summarises or depends on what a module does, and no line
of the core names a module. Adding or removing a module changes the wiring
file and the module's own files, and no line of the core.

The start refuses, naming the port and the wiring line, when the catalog is
broken: a name with two writers, an input bound to nothing, two types on one
wire, a cycle, or a declaration without its built-in value or help. A broken
catalog never runs, and the battery starts the index, so it fails before a
merge.

## A module

A module is one Go package that declares, by **local name** only:

| it declares | what it is |
|---|---|
| **inputs** | the names it reads, as fields of one input struct, tagged with a local port name |
| **outputs** | the names it writes, each with its type, built-in value and one help line |
| **config** | its keys, each with a type, a built-in value and one help line. A key is an input like any other, under `<instance>/config/<key>`; the module never learns where the value came from |
| **commands** | the functions a person or agent calls, in [Commands and help](#commands-and-help) |
| **requests** | for an I/O module only: the verbs it accepts from others, in [I/O modules and compute modules](#io-modules-and-compute-modules) |
| **the I/O flag** | for an I/O module only: it marks the module as one that touches the outside (v5's `q.IO()`). A module without it is a compute module, and the battery's import rule reads the flag, in [Testing](#testing) |

A compute module's run is pure: the module reads its input struct, computes,
and answers one commit of its outputs. It calls nothing else; it never reads
the store and never reaches the outside. An I/O module's run reaches its one
outside thing and nothing else, in
[I/O modules and compute modules](#io-modules-and-compute-modules).

The shape:

```go
type openIn struct {
    Issues []Issue `index:"issues"` // a local port; the wiring binds it
}

var Module = index.Declare("issues", "The issue rules.",
    index.Derived("open", 0, // output port "open", built-in value 0
        "The issues a box can take now.",
        func(in openIn) (int, error) { return countOpen(in.Issues), nil }))

func init() { index.Register(Module) }
```

| v5's contract | SE |
|---|---|
| inputs, outputs, config | **now** |
| families (key segments in a name) | **now**: the session log and the issues need them |
| actions: a run answers a list of requests to I/O modules, and a continuation reads their answers | **now**, without undo: SE's commands mostly act on GitHub and the disk |
| waves: heights at start, each module runs once per change, lowest first, after everything it reads has settled | **now**, single-threaded: it is what keeps a module from reading a new value beside a stale one. Demand (running only what someone watches) **later** |
| folds over session events | **later**, when a module needs state reduced from the session log |
| state and debug (a module's insides and diagnosis switches) | **later**, and left out of the contract until then |
| config layers (environment, local file, contexts, overrides) | **later**: until then a config value is its built-in value or the wiring file's |
| processes, the NATS bus, placements, leases, operations, views, the `files/` mirror | **not taken**: one daemon process, in-process calls, and no files module |

## I/O modules and compute modules

Only **I/O modules** (#44) touch the outside: processes, the disk, the clock,
the network and GitHub, one I/O module per outside thing ([principle 6](principles.md)).
An I/O module commits what comes in as its outputs, such as the session events
the plugin posts, and accepts **requests** going out, such as "create this
issue". It holds no business logic.

A **compute module** reads a snapshot and commits its outputs. When it must act
on the outside, its command answers a list of requests addressed to its own
local request ports; the wiring binds each port to an I/O module's verb, and
the core delivers them in order. A failed request stops the list and the
command fails with its reason. A continuation reads the answers and may answer
the next list, so each step stays pure.

There is **no files module**: nothing mirrors the tree into the index. A module
that needs a file asks the disk I/O module for it in a request.

## The wiring file

One file, src/internal/index/wiring.yaml, names the module instances and
binds their ports. It is the only place that knows the global layout. It sits
beside the core's package, src/internal/index, because `go:embed` reaches no
file above the embedding package, so v5's spec/wiring.yaml cannot be
embedded from there.

| an entry | what it says |
|---|---|
| an instance | its name and its module, such as `issues: { module: issues }`. One module can run as two instances with different config |
| a wire to a name | `issues.open: issues/open`. Ports bound to one name meet there, and neither side knows the other |
| a wire port to port | `briefing.open: issues.open` |
| an output with no wire | readable as `<instance>/<port>` |
| an input with no wire | the start refuses, unless the wiring marks it `built-in` |
| a config value | `issues: { config: { lease: 3h } }`, under `<instance>/config/<key>` |
| a request port | bound to an I/O module's verb, such as `issues.create: github.create-issue` |

The file is embedded in the `se` binary, so an installed `se` carries the
wiring it was built with, and the daemon reads it at start. A change to the
wiring or to any port restarts the daemon.

## Where it runs

The index runs in the per-workspace daemon, `se serve`, the process that
already receives the plugin's events. The daemon is the index's host: it holds
the lifetime lock, publishes its endpoint in `.se/.runtime/daemon.json`, loads
the wiring, starts the modules, and ends when idle.

Every reader goes through the daemon, over loopback HTTP with the endpoint's
token:

| the reader | how it reads |
|---|---|
| the plugin's bridgehead | posts each session event, which the session I/O module commits; runs `/se` words through the `se` binary, as today |
| an `se` command | the binary is an adapter: it finds or starts the daemon, posts the command with its arguments, and prints the reply |
| `/se ui`, `se help`, the manifests | read the collector's catalog from the daemon and render it |
| any later adapter (a REST API, an MCP tool list) | reads values by name, calls commands by name, and subscribes to changes, the same three verbs |

### What a command waits on

A person waits on every `se` command, so the adapter follows
[principle 9](principles.md): feedback within 1 second, never blind.

| the daemon | what the command waits on | what the person sees |
|---|---|---|
| answers | the post and the command's reply | the reply |
| does not run, or does not answer | the daemon's start: `se serve` takes the lock, loads the wiring, starts the modules and publishes `daemon.json`, then the post | after 1 second without an answer, one line on stderr: the daemon is starting for this workspace; then the reply |
| does not answer within the start wait (10 seconds today) or exits at start | nothing more | an error naming the daemon log; the command does not run |

The adapter never runs a command in its own process when the daemon is slow:
the index has one host, and a second one would give its names a second writer.
The cold start is the command's longest wait, so the daemon records its
duration like any command's, and a soft budget in
[spec/budgets.yaml](budgets.yaml) reports when it grows. The core's issue
(step 1 of the migration) sets that budget from its first measurement.

## Commands and help

A module declares its own user-facing commands in its own files ([principle 18](principles.md)).
It marks a function as a command with:

| the field | what it is |
|---|---|
| name | the words that call it: `issue land` |
| usage | the command line after the name, with its flags |
| summary | one short line, no flags |
| help | what the command's help says beyond the usage |
| group | the heading it stands under in the help listing |
| offered | in a session as `/se <name>`, and whether as a `/se ui` button |
| installed | answered by the installed `se` even when the session works in an SE checkout, whose own `se` answers every other `/se` word: `on`, `restart`, `update` |
| class | `interactive`, a command a person waits on, which answers from the snapshot within its budgets in [spec/budgets.yaml](budgets.yaml); or `batch`, one that must write or that the fleet, a hook or the battery runs ([principle 9](principles.md)) |

The command runs like any other run: it reads a snapshot of the module's
inputs plus its arguments, and answers a reply, a commit of the module's own
outputs, and requests to I/O modules.

**A module's help talks only about that module.** It never explains, lists or
refers to another module's commands or behaviour.

**The command registry is only the collector.** It gathers what modules
declared and holds no text of its own about any command. Every adapter renders
what it gathered: the CLI (`se ...`), the plugin's `/se`, the `/se ui` buttons,
the help listing and the generated manifests, and any future adapter such as a
REST API. A new module's commands and help appear everywhere without touching
an adapter or the core. Today's registry (`src/cmd/se/commands.go`, one file
per command) becomes that collector, and each command, with its help, moves
into the module that owns its behaviour.

**The `/se ui` panel is a grid of mechanical buttons**, the owner's rule of
2026-10-14. Its shape is the renderer's, not a module's: `se ui` answers the
buttons the catalog offers with the most a row holds, the `cli` instance's
`columns` config value in the wiring file (3 today), and the plugin's drawing
of the pane (`gridOf` in `src/plugin/hooks/register.tsx`) lays them out:

- a row holds at most `columns` buttons, the on/off toggle top left counted;
  the next button starts the next row;
- every cell is as wide as every other, so the columns align from row to row
  and a short last row stays to the left;
- every button is labelled with its command's name.

## Testing

Every part tests itself alone ([principles 7 and 8](principles.md)):

| what is tested | against |
|---|---|
| a compute module | the **fake index** (v5's `q/qtest`): the test seeds the inputs and config the module reads, by local name, runs it (a derivation or a command with arguments), and asserts the outputs it commits and the requests it answers, handing each request its answer |
| an I/O module | the fake index and the fake of its outside, with one contract suite run against the fake and the real thing, in the shape [io.md](io.md) sets (#44) |
| the fake index | one contract suite, run against the fake and the real core in process: the fake speaks the module contract and nothing more |
| the index core | fixture modules that declare, read and write as a test scripts them |
| every command declaration | generic cases over the catalog: each has a summary, help and group, and every adapter shows the same text |

This is principle 8 applied to modules, not an exception to it. A behaviour
lives in one module, and that module's outermost interface is what it
declares: its commands and its derivations. Its test drives that interface on
the fake index, which is the fake principle 8 asks for. The CLI, `/se` and the
other adapters add no behaviour of their own: they render and dispatch what
the collector gathered, so the generic cases over the catalog test them once
for every command. No test drives one command's behaviour through an adapter
again; that would test it twice.

No module test starts the daemon, and no compute module talks to anything but
the index. A compute module imports the index contract and the pure standard
library only: no package that reaches the outside, such as `os`, `os/exec`,
`net` or `net/http`, and no read of the clock (`time.Now`). An I/O module, one
that carries the I/O flag, imports the index contract, the standard library
and what its outside thing needs. A rule in the battery reads the flag and
holds both once the first module lands.

## The migration

Each step is its own issue, and SE works after each one.

1. **The core, the fake index and the wiring loader**, with src/internal/index/wiring.yaml, hosted in `se serve`, tested with fixture modules. It measures the daemon's cold start and sets its budget. No module moves yet.
2. **The collector.** The command registry gathers declarations, and the CLI, `/se`, `/se ui`, the help and the manifests render from it. Commands keep their current files and get the declaration shape.
3. **The session event log** becomes the session I/O module: the bridgehead's posts come in as the `session/<id>/events` family, and it keeps the log file. It is the first real module and the smallest.
4. **The issue rules** (next, new, land, review and the tree rules in `src/internal/issues`) become compute modules on the GitHub I/O module (#44), and their commands move with them.
5. **The rest of the fleet's work**, one module each: retro, overhaul, review brief, fleet, briefing, and the checks behind `se rules` and `se manifest`.
6. **The daemon's session commands** that need a running daemon (off, ui) move into a session module. The host's own commands stay with the adapter (open question 1), and the daemon's process stays the host, not a module.

## What v5 learned

- One value computed in two places drifts: v5's sidebar and window counted open tickets two ways and disagreed, and the fix touched eleven files. One writer per name.
- A catalog fixed at start, checked at start, catches a missing writer before a merge. A name added at runtime escapes the check; families give keys without new names.
- A generic "load this file into that name" gives a name a second writer. There is none.
- A module fed twice by one change, run on every push, reads a new value beside a stale one. Heights and one run per change prevent it.
- A pure run on one snapshot is testable with a struct and no index; the price is declaring every input up front.
- One declaration rendered by every surface removed copies that had drifted apart. No surface keeps a list of its own.
- A fake without a contract suite drifts from what it stands for.

## Open questions for the owner

1. **The host's own commands.** `se serve`, `se start` and `se stop` run before any index exists; `se on` starts the daemon, `se status` says whether one answers, and `se restart` and `se update` replace the running one, so none of the seven can be answered by a module inside the daemon. Proposed: they stay the CLI adapter's own commands, talking only about the adapter. Or should a module the daemon always loads declare them?
2. **Where modules live.** Proposed: the core and its fake in two packages under `src/internal`, and each module one package under a modules folder. v5 put one module per file, several per package; is a package per module right for SE?
3. **Actions without undo.** SE takes requests now and leaves v5's undo step out. Is a failed list that stops without rolling back acceptable for GitHub and the disk?
4. **Config layers.** Until a module needs one, config is the built-in value or the wiring file's. Which layer comes first when one is needed: environment or a local file?
5. **Pushes over HTTP.** Adapters read and call today; a subscription stream (for `/se ui` to update live) waits until an adapter needs it. Is that the right order?
