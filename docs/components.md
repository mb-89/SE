# Components: one way to find them

SE, obs and kern build with parts that live in other repositories: kern itself, obs, obs's adapters
and styles, and later kinds. This note owns how every such part is named, marked, found on the
checkout's remotes, pinned and marked required or optional, and what SE's start does when a
required one is missing. It also owns the contract every application keeps: its top-level files,
its one main command, and that command's `components` verb.

It is a design: [The packages](#the-packages) lists the implementation in order, and until each
lands the README describes what runs. It extends obs's design of its own components (obs's
`spec/design_input/components.md`, work issue obs#860) to every host, and it replaced the address in
each `se.toml` module entry by the name alone ([README "Modules"](../README.md#modules)).

## A component

Every part is a **component**; "plugin", "part" and "module" name nothing else
(the person's decision of 22 Nov 2026).

- A component is used by **hosts**. SE is the root host; kern and obs are SE's components; obs is
  itself a host, whose adapters and styles are its components; kern is a component of SE and a host
  of its own components.
- A component lives in its host's tree or in a repository of its own. One in its host's tree, such as
  kern's `components/github`, is part of its host's release: nothing finds it, and no list names
  it. This note is about the second kind, a **component repository**.
- A component knows nothing of its hosts. It can be required by several hosts, and it can run by
  itself.

A component repository carries three things, and nothing that names a host:

| What | Form | Example |
|---|---|---|
| The mark | a file `component.toml` at the root of a release's tree, whose `name` is the component's name | kern's `component.toml`, `name = "kern"` |
| Its name | the repository's name, compared without case as the host compares it: 1 to 32 letters, digits and dashes, starting with a letter or digit | `kern`, `obs`, `obs-html` |
| Its releases | tags `v<major>.<minor>.<patch>`; the release is the commit the tag points to | `v0.14.1` |

The release tags are the ones SE's component pins already read, so kern's, obs's and SE's existing
releases are releases of their components as they are.

### The mark

A repository is a component where its release holds the mark (finding reads the release the pin
chooses, listing the newest); nothing else marks it, and no repository topic does (the person's
decision of 22 Nov 2026: "One of them is enough"). The mark is one file for every kind, not one
per host, so a component that two hosts use carries one mark and names neither.

- **The file is kern's declaration file.** A kern component is declared by a `component.toml` at
  its folder's root, which kern's reader reads (`index.ParseDeclaration`), so in a repository of its
  own that file is its mark, and its `name` and `help` are the mark's. Every other kind carries a `component.toml` with those two keys
  alone, as no other reader reads it there:

  ```toml
  name = "obs-html"
  help = "obs's HTML adapter: renders an obs Document as one HTML page"
  ```

- **Its two keys are kern's**: `name`, the repository's name, and `help`, the one line `components
  list` shows. kern's reader refuses a key it does not know, so the mark adds none; a host reads the
  rest of a release as its kind needs.
- **The kind is what the tree holds**, so it needs no key: obs checks for `adapter.json` beside the
  mark (an adapter), kern for a declaration with `contract` (a kern component). The entry file keeps
  its contract and gives up its own `name` where it has one (obs's `adapter.json`), so the name is
  in one place.
- **Hosts are components too**: kern's and obs's repositories carry a mark at their root, as SE
  finds them. SE's own repository carries none: SE is no component ([method.md](method.md)).

## The requirement list

**The requirer holds the list.** Each host keeps one list of the components it uses, by name, in its
`se.toml`, as the table `[components]`:

```toml
[components.kern]
go = "components/go.mod"          # the pin: the version that go.mod requires

[components.obs]
version = "^4.0"                  # the pin: a range of its release tags

[components.style]
version = "^1.4"
optional = true                   # absent: required
```

- An entry names a component and its pin, and nothing else: no address, no owner, no host, no
  provenance. The pin keys stay as the README's [Modules](../README.md#modules) defines them (`ref`,
  `version`, `go`, `path`), and `se.lock` records each pin's version and commit.
- `optional = true` marks a component the host works without; an entry without it is **required**.
  Required is the default, since a missing required component should fail where it is declared, not
  later as a half-working command.
- SE's list is `kern` and `obs`, both required: SE needs kern for everything mechanical, and obs for
  every deck, its documentation, its Timeline and its templates (the person, 22 Nov 2026).
- obs's list holds the adapters and styles that leave its tree. Neither obs's nor kern's list holds
  `se`: SE is not a component, but the method that works on them, and no project pins it
  ([method.md](method.md)). Each host says required or optional for its own entries only.
- The list is written by `components add` and `components remove`
  ([The `components` verb](#the-components-verb)) as `uv add` writes `pyproject.toml`; an edit by
  hand is read the same way.

A machine that needs another place, such as a mirror or a local checkout, says so in the
machine-local file ([README "Modules"](../README.md#modules)), which wins over finding and is never
committed.

## Finding a component

Finding `<name>` for a checkout reads only the checkout's own Git configuration:

1. **The remotes**: `origin` first, then the checkout's other remotes in the order Git lists them,
   each by its configured address. Nothing committed names a remote.
2. **The owners**: each remote's host and owner come from its address, as SE's home does
   (`scripts/se_home.py`, kern's `kern/home`); a remote of no such form, such as a local path,
   offers nothing.
3. **The repository**: the repository named `<name>` beside the remote, reached the way its remote
   is: the remote's address with `<name>` in place of the remote's repository.
4. **The releases**: its tags are read without fetching objects (`git ls-remote --tags`), and the
   pin chooses among the `v` tags.
5. **The mark**: the release the pin chooses is fetched, one commit without history, and is taken
   only where its tree holds a `component.toml` naming `<name>`. A release without it is no
   component, and finding goes on.
6. **The first offer wins**: the first owner, in the order of step 1, whose `<name>` offers a marked
   release the pin admits is where the component comes from. An owner reached by two remotes is read
   once, at its first place.

Finding a named component needs Git alone: no listing is read, so it works where GitHub's API does
not answer. Listing every component an owner offers is the one step that reads the API
([Listing every offer](#listing-every-offer)).

Another owner's components join by adding any one of that owner's repositories as a remote: its owner
is searched like origin's.

A component that meets a host's contract under the same name stands in for another: a fork or a
rewrite named `kern` under a remote's owner is kern, if its release carries the mark and the pin
admits it.

A remote that cannot be read is one line naming the remote and Git's message, and finding goes on
with the next owner.

### Listing every offer

`components list` shows what every owner offers, not only the names a list holds, so it reads each
owner's repositories and each one's mark:

1. **The owner's repositories**: GitHub's REST API, `GET /users/<owner>/repos` (an organization's
   `GET /orgs/<owner>/repos`; the login's own account `GET /user/repos?affiliation=owner`, which
   names its private ones), 100 a page, with the person's login where the machine holds one.
2. **Their releases**: each repository's `v` tags by `git ls-remote --tags`, as step 4 above; a
   repository without one is no component, and nothing more is read for it.
3. **Their marks**: the newest release's `component.toml`, `GET
   /repos/<owner>/<repository>/contents/component.toml?ref=v<version>`; an answer 404 is no mark.

Picked: the contents API, not code search. Code search indexes only a repository's default branch,
not a release's tree, so it would answer for a mark the release may lack. It also needs a login
(10 searches a minute) and leaves out repositories it has not indexed, so a listing could miss a
component.

| Read | Calls for an owner of N repositories, T with a `v` tag | Measured |
|---|---|---|
| The repositories | ceil(N / 100) API calls | blocked in a Claude cloud session (403, 22 Nov 2026) |
| The tags | N `git ls-remote` reads, eight at a time; no API call | 0.40 to 0.60 s each, so about 13 s for N = 200 |
| The marks, first run | T API calls | not measured: blocked in the same session |
| The marks, after it | one per repository whose newest tag moved | |

- **The limit**: without a login GitHub answers 60 API calls an hour, so a first listing of an owner
  with more than about 50 tagged repositories needs one; with a login it is 5,000. A listing that
  reaches the limit lists what it read and names each owner left unread, the reset time and the
  remedy, a login.
- **The cache**: each owner's listing lives in the machine's cache (SE and every kern application:
  `~/.se/cache/components/<host>/<owner>.json`; obs: its machine folder), never committed.
  - It keeps each repository's newest tag, that tag's commit, and the mark, help line and
    `[components]` read at that commit. A commit's tree never changes, so an entry is read again
    only where the tag moved.
  - A `list` within an hour of the last reads nothing; `--refresh` reads again.
- **Offline or refused**: an owner whose API does not answer is listed from its cache, with one line
  naming the owner, the cache's age and why it was not read. An owner never read is one line, and
  `list` still shows what is installed.

### Several hosts, one tree

Resolving is recursive. From the root, each required or optional name of a host's list is found and
placed at its pin; then that component's own `se.toml` `[components]`, read from its release, is
resolved the same way.

- **One version per name**: a name the tree reaches twice is one component. Its pin must admit one
  release for every host that names it; where the pins admit none in common, the resolution fails
  naming both paths and both pins. obs installs one version of a component per machine for the same
  reason (obs's `spec/design_input/components.md`, Installed components).
- **A name already on the path** is that component: an entry that names a host above it on the
  path is that host itself, and its pin is checked against that host's version, not resolved again.
- **Placing is the host's**: a kern application places its components as clones in
  `.se/modules/<name>`; obs places its own in its machine folder. Finding is shared; where a host
  keeps what it found is not.

The order of remotes puts `origin` first rather than in Git's alphabetical order alone, so that a
fresh clone takes each component from the owner it came from ([Finding kern](#finding-kern)).

### Breaking releases beyond a pin

A component cannot know who relies on it, so only its host sees that it moved past the host's pin
(work issue SE#1719). `se_modules.py breaking` looks, for every pin in the tree:

- **The pins**: the root's and each component's own, read as [the tree](#several-hosts-one-tree)
  resolves them, nested ones included. Where two hosts' pins admit no common release, `sync`
  refuses; the check reports each pin instead.
- **The newest release**: the highest `v` tag of the component's first offer in the order of
  [Finding a component](#finding-a-component), read without fetching objects.
- **Breaking**: the newest release lies beyond what the pin admits and has a higher major than
  the pin's base, or below 1.0 a higher minor (SE#1647). The base is a range's lowest version, a
  `go` pin's version, or a `ref` pin's release at its commit; a `ref` without one is not judged.

It prints one line per finding, naming the holder, the pin and the newest release (`obs-html pins
obs ^10, newest 11.0.0`), and the path for a nested holder. Where nothing moved it prints one line
saying so; `--all` lists every pin with its verdict and the run's notes. It exits 0 either way,
and 1 with a message only where the listing fails: the tree does not resolve, or no offer names a
component's releases.

The check changes no pin, no lock and no checkout, and files no issue: what to do is the person's
decision. It places a release in `.se/modules/<name>` where `sync` would, to read that
component's own list. Every retro runs it (`retro.py collect`), and SE's boot lists its pins with
their locked versions after the start greeting, its `--upgrade` moving each lock within its pin
([README "Boot"](../README.md#boot)).

Moving a pin across such a release follows the sections of the component's upgrade guide between
the two versions, `upgrade_guide.py show` ([docs/upgrading.md](upgrading.md)); each component keeps
its own guide in that shape.

## Runtimes

kern runs components in Go or, over its bus, in Python, and a component may need a browser or Node
besides: each needs its runtimes on the machine. They are collected from the tree, as npm's
`engines`, Cargo's `rust-version` and uv's `requires-python` sit beside the dependencies they
belong to (the person's decision of 22 Nov 2026, runtimes blessed).

- **Each component declares its own**, in its `se.toml` beside its `[components]`, as the table
  `[runtimes]`: a runtime's name and the range of its versions it admits, in the form of a
  component's `version` pin ([README "Modules"](../README.md#modules)). The root declares its own
  the same way.

  ```toml
  [runtimes]
  python = "^3.12"                  # 3.12.0 up to 4.0.0
  uv = "^0.5"
  ```

- **The names** are the runtimes SE can ask for their version, `go`, `node`, `python` and `uv`,
  each by its own command (`scripts/se_runtimes.py` `PROBES`, where one line adds one); a name it
  cannot ask, or a range it cannot read, refuses naming the file.
- **The union over the tree**: resolving the tree ([Several hosts, one tree](#several-hosts-one-tree))
  reads each placed component's `[runtimes]` from its release, the root's first. A runtime two
  components name must meet both ranges; where they admit no common version, the resolution fails
  naming both paths and both ranges.
- **Got through RUNME**: a runtime the machine lacks is got by the `get` lines of that name in the
  root's `RUNME.conf`, run by the root's own RUNME (`RUNME.sh`'s header owns the line kind), so a
  machine gets a runtime one way whether RUNME or the tree asks for it.
  - The check writes `.se/.runtime/runtimes/RUNME.conf` with the root's `path` lines, a `need` per
    command that answers the runtime's version and those `get` lines, and runs `RUNME.sh` beside
    it; a command line runs in the root, as RUNME runs it there.
  - One line names each runtime got: `runtime go 1.23.0: got through RUNME.conf (for se -> lib)`.
- **Before any component runs**: the check runs once the tree is resolved and before its lock is
  written, so `sync` and the start of [Required and optional at start](#required-and-optional-at-start)
  stop before the core, or any component, starts. Where a runtime is still missing or found at a
  version a range refuses, they stop with one message naming each, its ranges, the components that
  need it and the remedy:

  ```text
  SE cannot start: the component tree needs 1 runtime this machine lacks; no component runs until each is present:
    go ^1.22 (for se -> lib): missing; RUNME.conf names no way to get it: add a line get go <way> <what> (RUNME.sh's header), or install go yourself
  ```

  RUNME's own last line is the remedy where its `get` lines failed (`go is missing; run: <command>`);
  a runtime found outside its range is never replaced, as the machine's other users may need it.
- **A tree that declares none asks nothing**: no runtime's command runs, so a start of such a tree
  keeps its budget.

## Required and optional at start

SE's start (`scripts/se_start.py start-components`, before the core starts) resolves the tree from
the checkout's lists:

- **From what is placed, first**: a component whose clone exists at its locked commit is found
  without asking any remote, so a start with every component placed stays within its budget and
  works offline.
- **A required component missing** anywhere in the tree stops the start with one message, and SE
  works with nothing half-started:

  ```text
  SE cannot start: the required component obs is missing (se -> obs).
  No remote's owner offers a repository obs whose release carries component.toml and is admitted by its pin ^5.0 (read: origin).
    origin: github.com/<owner> offers no repository obs
  Add a remote of an owner that offers it: git remote add <remote> <address>
  ```

  It names the path from the root, the remotes read, and the remedy, a remote that offers the
  component. A remote that could not be read is named with Git's message, since an offline machine
  with no clone has not found the component either.
- **An optional component missing** is one line naming its path, and the start goes on:
  `optional component se -> obs -> style not found on any remote's owner`.
- **A lock that disagrees**: a found release whose tag points to another commit than `se.lock`
  records stops the start naming both commits and the remedy, `se components update <name>`, so a
  stand-in never replaces a locked component silently.
- **What is due**: the greeting's lines for a component offered and not installed, or installed with
  a newer release, come from the project's own main command, `<main> components list --json`
  ([The `components` verb](#the-components-verb)); the main command is the `run` line of the
  project's `RUNME.conf`, so no setting names it.

obs and kern, run as roots of their own checkouts, check their own lists the same way, by the same
rules ([The one owner](#the-one-owner)).

## The application contract

Every application, SE, obs, kern's bare core and each one `se new app` makes, keeps one shape, so a
person who knows one knows all (the person's decision of 22 Nov 2026):

- **RUNME**: `RUNME.sh`, `RUNME.ps1` and the project's `RUNME.conf`, the same RUNME in every
  project (`RUNME.sh`'s header owns its format). `RUNME <arguments>` installs what the machine
  lacks and runs the main command with them, so `./RUNME.sh components add obs-html` and `obs
  components add obs-html` are the same call.
- **README**: `README.md` says what the application is, how to get it running (RUNME), and its
  commands, as the main command's `help` prints them.
- **Few top-level files**: RUNME's three, `README.md`, `LICENSE`, `AGENTS.md`, `se.toml` and
  `se.lock`, `wiring.toml` for an application on kern, `docs.md` where documentation is built, and
  the language's own project files (`pyproject.toml` and `uv.lock`, `go.mod` and `go.sum`). Every
  other file lives in a folder.
- **One main command**: every subcommand a person or an agent types is a verb of the main command,
  reached through it and through RUNME. There are no sibling programs (`obs-components` beside
  `obs-document`): a verb a second program would carry is a verb of the main one.
- **`help`**: `<main> help`, `--help` and `-h` list every verb with its one line, the verbs hosts and
  hooks call apart, and `<main> help <verb>` gives that verb's options; `./RUNME.sh help` prints the
  same, as RUNME owns no option.
- **`components`**: every application has the verb below, with the same subcommands, output and exit
  codes ([The `components` verb](#the-components-verb)).
- **Its dependencies in one list**: `RUNME.conf` declares everything the application needs on a
  machine, GitHub among them ([GitHub, a hard dependency](#github-a-hard-dependency)), and how
  the machine gets each runtime its component tree needs ([Runtimes](#runtimes)).

The one step outside the main command is placing the main command itself: `RUNME.conf`'s `get`
line for it (SE's `bootstrap.sh --binary`) runs before the main command exists, and no person types
it.

## The `components` verb

Shaped like uv's `add`, `remove` and `lock --upgrade` (the person, 22 Nov 2026): it manages the
host's [requirement list](#the-requirement-list), its lock and what is placed, and it lists what
every remote's owner offers. On kern it is one of kern's own verbs (`kern/cli/verbs.go`), so every
application on kern has it unchanged; obs, which is not on kern, implements the same verb by the
same rules ([The one owner](#the-one-owner)).

```text
<main> components list [--nested] [--refresh] [--json]
<main> components add <name> [<version>] [--optional]
<main> components remove <name>
<main> components update [<name>]
<main> components sync [<name>...]      (hosts: what the start runs)
<main> components path <name>           (hosts: the folder a component is used from)
```

Exit codes: 0 done, 1 refused (the message names the cause and the remedy), 2 a usage error. Every
refusal leaves the list, the lock and what is placed as they were: a verb that changes them writes
the list and the lock only once everything it fetched is placed and prepared.

### list

One row per component the host's tree holds and per component any remote's owner offers, sorted by
name ([Listing every offer](#listing-every-offer)):

```text
component  installed  newest  pin   need      from
kern       0.14.1     0.15.0  go    required  github.com/<owner>/kern  (outside the pin)
obs        5.0.0      5.3.1   ^5.0  required  github.com/<owner>/obs   (update)
obs-html   -          1.4.0   -     -         github.com/<owner>/obs-html
```

- `installed` is the placed version, `-` where none is; `newest` the newest marked release offered,
  `-` where no owner offers one; `pin` and `need` the list's entry, `-` for a component the list
  does not name; `from` the first owner that offers it.
- `(update)` marks a newer release the pin admits, which `update` takes; `(outside the pin)` a newer
  one it does not, which `add <name> <version>` takes.
- The lines under the table name each owner read from its cache or not read, as the listing says.
- `--nested` lists, below each component, the components its own list names in turn, indented by
  their depth, with each one's pin and need. An installed component's list is read from its placed
  clone; an offered one's from its newest release, one cached read each.
  - A name already above it on the path is shown as `(above)` and not expanded.
  - Two pins of one name that admit no common release are one line naming both paths and both pins,
    as resolving would fail; `list` itself does not fail.
- `--json` prints the same as one JSON object, `{"components": [...], "unread": [...]}`, each
  component with `name`, `help`, `installed`, `newest`, `pin`, `need`, `from`, `update` and, with
  `--nested`, `components`; the start's greeting reads it.

### add

`add <name> [<version>]` finds `<name>` ([Finding a component](#finding-a-component)), fetches its
release, prepares its environment at once, then writes the list and the lock:

- **The version**: none takes the newest marked release and writes the pin `^<major>.<minor>` of it;
  `x.y.z` takes that release and writes `=x.y.z`; a range (`^5.2`, `~5.2`) takes the newest it
  admits and writes it. `--optional` writes `optional = true`.
- **Its own components**: the release's `[components]` are resolved and placed too, as the tree
  ([Several hosts, one tree](#several-hosts-one-tree)), each prepared the same way.
- **The environment, prepared at once**, from what the release's tree holds, so a component that
  `add` placed runs on its first use without a hidden step:
  - `pyproject.toml`: `uv sync --locked` in the placed tree, which builds its environment there; a
    release without `uv.lock` is refused, as its environment could not be reproduced;
  - `go.mod`: `go build ./...` in the placed tree against the host's kern pin, which fetches its
    modules and shows a failure to build at once;
  - neither: nothing to prepare.
- **Its runtimes**: the tree's [Runtimes](#runtimes) are checked, and what `RUNME.conf` gets got,
  before anything is prepared; one still missing refuses.
- **Output**: one line per component placed, with its version, pin, owner and what was prepared,
  `added obs-html 1.4.0 (^1.4) from github.com/<owner>/obs-html; prepared: uv sync --locked (2.1
  s)`.
- **A name already in the list**: with a version, it is pinned again by what the version admits,
  and its line says from and to; without one, or at the same pin, it is `obs-html 1.4.0 is already
  added`, exit 0.

`add` refuses, naming:

| Cause | The message names |
|---|---|
| no owner offers `<name>` | the remotes read, each with why it offered nothing, the names offered, and the remedy, a remote of an owner that offers it |
| no release the version admits | the versions offered and the form `x.y.z` or a range |
| the release carries no mark | the release and `component.toml` naming `<name>` at its root |
| the tree's pins admit no common release | both paths and both pins |
| a runtime the tree needs is missing or outside its range | each runtime, its ranges, the components that need it and the remedy, as [Runtimes](#runtimes) says |
| preparing failed | the step's command, its exit code and its output's last line |
| GitHub cannot be reached | the remote, Git's message, and `RUNME.conf`'s line that declares GitHub |

### remove

`remove <name>` takes the entry out of the list and the lock, then removes its placed clone, its
environment, and every placed component no other part of the tree still reaches. It prints one line
per component removed, `removed obs-html 1.4.0`.

It refuses, naming: a name the list does not hold (with the path of the component that requires it,
where one does: remove it from that host); and a placed clone with local changes, which is never
overwritten (its path and `git status`).

### update

`update` moves every component of the tree, `update <name>` that one, to the newest marked release
its pin admits: it finds the component again with its lock aside, places and prepares the release,
and writes the lock. It never changes a pin.

- One line per component: `obs 5.0.0 -> 5.3.1`, or `kern 0.14.1 is the newest its pin go admits
  (0.15.0 offered: components add kern 0.15.0)` where a newer one lies outside the pin.
- A `go` pin follows its `go.mod`: `update` names the `require` line to change, as `go.mod` is the
  pin's owner. A `ref` pin moves to the newest commit on the component's `main`.
- It refuses as `add` does, and for a name the list does not hold.

### sync and path

`sync` places the tree at its locks, finding only what is not placed at its locked commit, and
prepares what it placed; SE's start runs it
([Required and optional at start](#required-and-optional-at-start)).
`path <name>` prints the folder a component is used from, for tools that load it. Both are verbs
hosts call, listed apart in `help`.

## GitHub, a hard dependency

GitHub, its Git service and its REST API, is a hard dependency of every application with this verb
(the person, 22 Nov 2026: "GitHub is going to be a hard dependency, right? That's okay").

- **Declared once**, in the one list of what an application needs on a machine, its `RUNME.conf`,
  by a new line kind `service <name> <url>`:

  ```text
  service github https://api.github.com
  ```

  `RUNME.sh`'s header owns the kind. RUNME does not check it on each run, so a start with every
  component placed still works offline. The `components` verb and SE's `doctor` read it: a refusal
  for want of GitHub names this line.
- **Who declares it**: every application, as each has the verb: SE's, obs's, kern's template (so
  each application `se new app` makes has it) and a component that runs by itself. A component that
  never runs by itself, such as an adapter, declares nothing: its host reads GitHub, not it.
- **What needs which**: `add`, `remove`, `update` and `sync` need Git alone, reaching GitHub as the
  checkout's remotes do; `list` also reads the API.
- **Hosts other than GitHub**: a remote on another host is found by Git as step 3 says. Its owner's
  offers are not listed: `list` names the remote and that its host offers no listing.

## The one owner

This note owns the rules; two finders implement them, each held to them by its own tests of this
note's cases:

- **kern's**, in Go, behind kern's `components` verb, for every application on kern, SE included.
  It is kern's, not SE's, as every application on kern has the verb; SE adds no code to it.
- **obs's**, in Python, behind `obs components`: obs is not on kern and pins no SE
  ([method.md](method.md)), so it cannot call kern's. It keeps what is obs's: its kinds and entry
  files, installing into its machine folder, `components.json`, and recording what built a page.

SE's `scripts/se_modules.py` was SE's finder; it gives finding to kern's verb, and keeps only what
SE's Python reads of `se.toml` and `se.lock`.

- **Finding kern needs no kern.** The `se` binary arrives as a release, downloaded and checked
  ([go-core.md "How the binary arrives"](go-core.md#how-the-binary-arrives)), so `se components
  sync kern` runs before any kern clone exists.
- **A checkout that builds `se` from source** (no release matches it) first downloads the newest
  released `se` of its home and runs its `components sync kern`; only a home with no release at all
  stops, naming that it has none.
- **At start**, the placed check reads `se.lock` and the clones, with no finder. Where a component
  is missing, the start places the binary in the foreground, as `bootstrap.sh --binary` does (about
  1 s; finding then fetches the component anyway), and runs `se components sync`.

## Finding kern

kern was pinned from its own repository by a relative address, `url = "../kern.git"`
([go-core.md "Pinned from kern's own repository"](go-core.md#pinned-from-kerns-own-repository)),
which resolved to the repository `kern` under origin's owner. Finding kern by name gives the same
kern:

- **The same repository**: the first owner the finder reads is origin's, and the repository it takes
  there is the one named `kern`, the one `../kern.git` named. They differ only where origin's owner
  offers no marked `kern`: the relative address failed there, and the finder goes on to the next
  remote's owner.
- **The same release**: the pin stays the `require kern v<version>` of `components/go.mod`, resolved
  to the tag `v<version>`, and `se.lock` keeps its commit. A kern found elsewhere is taken only where
  that tag points to the locked commit, so every place a kern comes from builds the same `se`.
- **The same clone**: it is still placed in `.se/modules/kern`, which `components/go.mod` replaces
  `kern` by, so the Go build does not change.

## After components-finder and the start check

Both landed in se 8.0.0: #1634 `components-finder` (`scripts/se_modules.py` finds by name under each
remote's owner, among the repositories GitHub's search lists with the topic `component`) and #1636
`start-checks-required-components` (`se_start.py start-components`). This contract keeps what they
built and changes:

| What landed | What changes | Package |
|---|---|---|
| the mark: the topic `component`, read through GitHub's search (`se_modules.py` `TOPIC`, `github_listing`) | the mark is `component.toml` in the release ([The mark](#the-mark)); finding a name reads Git alone, and the topic is read nowhere | kern 1, se 4 |
| `SE_COMPONENT_LISTING` with `fake:<file>`, the tests' fake listing of marked names | the fake lists an owner's repositories, and the marks come from the fake Git door's trees | kern 1, se 4 |
| `se_modules.py sync`, `status`, `update`, `path` | `se components sync`, `list`, `update`, `path`, kern's verb; `add` and `remove` are new; the script keeps no command | se 4 |
| `[components]` with `optional`, `url` refused, the lock check, one version per name | unchanged: kern's finder reads the same list and lock by the same rules | kern 1 |
| the start's placed check, its stop message and its optional line | unchanged, but the message names the mark instead of the topic, and a lock that disagrees names `se components update <name>` | se 4 |
| the start's finding of a missing component through `se_modules.py` | `se components sync`, with the binary placed in the foreground first ([The one owner](#the-one-owner)) | se 4 |
| `[project] components`, the project's listing command, whose table the greeting parses | gone: the greeting reads `<main> components list --json`, the main command from `RUNME.conf` | se 4 |
| `se.py component add`, which scaffolds an ad hoc component ([README "Ad hoc components"](../README.md#ad-hoc-components)) | `se components new <name>`, so one verb owns components and `add` means one thing, as `uv init` and `uv add` differ | se 4 |

## Steps only the person takes

- **Once packages 3 and 4 have landed**, nothing reads the topics `component` and `obs-component`,
  and the person may remove them from the repositories that carry them. Nothing depends on it.
- **The topic `component` on kern and obs**, which package 3 of the earlier plan asked for, is no
  longer needed.

## Open points

- **Installing obs's required components**: obs installs a component only when the person chooses
  it, while a required one in obs's list must be present for obs to build. `obs components sync`
  places them; whether obs's build runs it on its own, or SE's start only reports a required one not
  placed, is the person's to decide. obs's package 3 ships the verb either way, and its build step
  waits for the answer.

## The packages

In order; each is one work issue. The earlier plan's packages 1 and 2 landed, the finder (#1634)
and the start check (#1636); its package 3, the person's topic step, is dropped ([Steps only the
person takes](#steps-only-the-person-takes)); its package 4, obs's, is package 3 here.

1. **kern: the `components` verb** (kern's repository). `cli/verbs.go` adds `components` with
   `list`, `add`, `remove`, `update`, `sync` and `path` as [The `components` verb](#the-components-verb)
   says, over a finder package in kern by [Finding a component](#finding-a-component) and
   [Listing every offer](#listing-every-offer), its cache, environment preparation and the tree's
   [Runtimes](#runtimes), whose check `scripts/se_runtimes.py` holds until then. kern's root
   gets its mark, `component.toml` with `name = "kern"`, which kern's own reader does not load as a
   component. kern's template carries the verb's `help` lines and `RUNME.conf`'s `service github`
   line, and `RUNME.sh`'s header the line kind. Tests on a fake listing and the fake Git door.
2. **obs-html: carries the mark** (obs-html's repository). `component.toml` at its root (`name =
   "obs-html"`, `help`), `uv.lock` committed for `add`'s `uv sync --locked`, releases tagged
   `v<version>`, and its one program `obs-html` with `help`. It lands before package 3, whose finder
   stops reading the topic.
3. **obs: one program, `obs`** (obs's repository). `obs-document` and `obs-components` become verbs
   of one program `obs`: `obs document` with today's `obs-document` options, `obs components` as
   [The `components` verb](#the-components-verb) says (`install` becomes `add`; `list`,
   `--nested`, `sync`, `path` are new).
   - `RUNME.conf` runs `obs` and declares `service github`.
   - `src/obs/components.py` finds by the mark, not the topic `obs-component` or the tag form
     `obs-component/<kind>/<name>/v<version>`; `adapter.json` gives its `name` to the mark.
   - `add` prepares with `uv sync --locked`; obs's root gets its mark; `se.toml` `[components]`
     lists its adapters and styles; `spec/design_input/components.md` points here.
   - Dropping two programs breaks obs's callers, so it is a major release of obs.
4. **se: `se components`** (se, at kern's and obs's new pins). `se components` is kern's verb, at the
   kern pin of package 1; `se_modules.py` keeps no command and no finder.
   - `scripts/bootstrap.sh` and `se_start.py start-components` run `se components sync`, as
     [The one owner](#the-one-owner) says.
   - The greeting reads `se components list --json`, and `[project] components` goes.
   - `se.py component add` becomes `se components new`; `build_docs.py` adds the html adapter with
     `obs components add obs-html` at obs's new major; `RUNME.conf` declares `service github`.
   - README "Modules", "Start and refresh", "Ad hoc components" and "Project settings";
     `tests/test_se_modules.py`, `tests/test_se_start.py`.
   - Removing `se_modules.py`'s commands and a setting breaks every project that calls them, so it
     lands as a major release of se.
5. **se: every command through `se`** (se). SE's script commands, each declared by its component's
   `component.toml` ([README "Commands as components"](../README.md#commands-as-components)), become
   verbs of `se`, so skills, agents and AGENTS.md name `se <command>`, not `uv run python
   <se>/scripts/<name>.py`. It changes the command line of every role, so it starts as a design
   package owned by [go-core.md "Migration"](go-core.md#migration).
6. **Each other application on kern** folds its sibling programs into its main command, and takes
   the verb with its kern pin: a work issue in each application's repository, filed by SE once
   package 1 has released.
