# Components: one way to find them

SE, obs and kern build with parts that live in other repositories: kern itself, obs, obs's adapters
and styles, and later kinds. This note owns how every such part is named, found on the checkout's
remotes, pinned and marked required or optional, and what SE's start does when a required one is
missing. It is a design: [The packages](#the-packages) lists the implementation in order, and until
each lands the README describes what runs.

It extends obs's design of its own components (obs's `spec/design_input/components.md`, work issue
obs#860) to every host, and it replaces the address in each `se.toml` module entry
([README "Modules"](../README.md#modules)) by the name alone.

## A component

Every part is a **component**; "plugin", "part" and "module" name nothing else
(the person's decision of 22 Nov 2026).

- A component is used by **hosts**. SE is the root host; kern and obs are SE's components; obs is
  itself a host, whose adapters and styles are its components; kern is a component of SE and a host
  of its own components.
- A component lives in its host's tree or in a repository of its own. One in its host's tree, such as
  kern's `components/github` or obs's `adapters/html`, is part of its host's release: nothing finds
  it, and no list names it. This note is about the second kind, a **component repository**.
- A component knows nothing of its hosts. It can be required by several hosts, and it can run by
  itself.

A component repository carries three things, and nothing that names a host:

| What | Form | Example |
|---|---|---|
| The mark | the repository topic `component` | the topic on kern's repository |
| Its name | the repository's name, compared without case as the host compares it: 1 to 32 letters, digits and dashes, starting with a letter or digit | `kern`, `obs`, `html` |
| Its releases | tags `v<major>.<minor>.<patch>`; the release is the commit the tag points to | `v0.14.1` |

The mark is one topic for every host, not one per host (`obs-component`, `kern-component`): a
per-host mark would make the component name its hosts, and a component that two hosts use would carry
two marks (the person's direction of 22 Nov 2026).

The name is the repository's name, not a name inside a tag: a host's list names a component by the
repository it looks for, so one repository is one component, and a tag holds only the version.

The release tags are the ones SE's module ranges already read, so kern's, obs's and SE's existing
releases are releases of their components as they are.

What a release holds is the host's business. A host checks the entry file it needs at the root of the
release's tree (obs: `adapter.json` for an adapter); a component's kind is what its tree holds, so
it needs no kind in its name or tags.

## The requirement list

**The requirer holds the list.** Each host keeps one list of the components it uses, by name, in its
`se.toml`, as the table `[components]`, which replaces `[modules]`:

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
  `version`, `go`, `path`), and `se.lock` records each pin's version and commit, as today.
- `optional = true` marks a component the host works without; an entry without it is **required**.
  Required is the default, since a missing required component should fail where it is declared, not
  later as a half-working command.
- SE's list is `kern` and `obs`, both required: SE needs kern for everything mechanical, and obs for
  every deck, its documentation, its Timeline and its templates (the person, 22 Nov 2026).
- obs's list holds the adapters and styles that leave its tree. Neither obs's nor kern's list holds
  `se`: SE is not a component, but the method that works on them, and no project pins it
  ([method.md](method.md)). Each host says required or optional for its own entries only.

The key `url` goes: a committed address is provenance, and finding by name answers where a component
comes from. A machine that needs another place, such as a mirror or a local checkout, says so in the
machine-local file ([README "Modules"](../README.md#modules)), which wins over finding and is never
committed.

## Finding a component

Finding `<name>` for a checkout reads only the checkout's own Git configuration:

1. **The remotes**: `origin` first, then the checkout's other remotes in the order Git lists them,
   each by its configured address. Nothing committed names a remote.
2. **The owners**: each remote's host and owner come from its address, as SE's home does
   (`scripts/se_home.py`); a remote of no such form, such as a local path, offers nothing.
3. **The marked repositories**: for each owner, once per run, the host lists the owner's repositories
   that carry the topic `component`, with the person's login where there is one (a private owner
   needs it). The repository named `<name>` among them is reached the way its remote is: the remote's
   address with `<name>` in place of the remote's repository.
4. **The releases**: its tags are read without fetching objects (`git ls-remote --tags`), and the
   pin chooses among the `v` tags as `se_modules.py` does today.
5. **The first offer wins**: the first owner, in the order of step 1, whose marked `<name>` offers a
   release the pin admits is where the component comes from. An owner reached by two remotes is read
   once, at its first place.

Another owner's components join by adding any one of that owner's repositories as a remote: its owner
is searched like origin's.

A component that meets a host's contract under the same name stands in for another: a fork or a
rewrite named `kern` under a remote's owner is kern, if the pin admits its release.

A host that offers no listing of an owner's repositories: the repository `<name>` beside the remote
is read directly, and the run prints one line naming the remote and that its mark could not be
checked. An owner the host cannot list (no login for a private owner, an unknown owner) is one line
naming the remote, the owner and why, and finding goes on with the next owner.

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
- **Placing is the host's**: SE places its components as clones in `.se/modules/<name>`, as
  `se_modules.py sync` does today; obs places its own in its machine folder through its install
  command. Finding is shared; where a host keeps what it found is not.

The order of remotes puts `origin` first rather than in Git's alphabetical order alone, so that a
fresh clone takes each component from the owner it came from, which is what the relative address
`../<name>.git` took ([Finding kern](#finding-kern)).

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
  No remote's owner offers a repository obs marked as a component with a release its pin ^5.0 admits (read: origin).
    origin: github.com/<owner> marks no repository obs as a component
  Add a remote of an owner that offers it: git remote add <remote> <address>
  ```

  It names the path from the root, the remotes read, and the remedy, a remote that offers the
  component. A remote that could not be read is named with Git's message, since an offline machine
  with no clone has not found the component either.
- **An optional component missing** is one line naming its path, and the start goes on:
  `optional component se -> obs -> style not found on any remote's owner`.
- **A lock that disagrees**: a found release whose tag points to another commit than `se.lock`
  records stops the start naming both commits and the remedy, `se_modules.py update <name>`, so a
  stand-in never replaces a locked component silently.

obs and kern, run as roots of their own checkouts, check their own lists the same way, by the same
rules ([The one owner](#the-one-owner)).

## The one owner

This note owns the rules of finding; SE's module resolution, `scripts/se_modules.py`, is SE's
finder: it answers, for a checkout and a name, the repository and the releases offered, in the
order above, and SE's start calls it. obs pins no SE ([method.md](method.md)), so obs's
`obs-components` cannot call it: obs's command implements the same rules itself, and points here
for them.

- obs's command keeps what is obs's: its kinds and entry files, installing into its machine folder,
  `components.json`, and recording what built a page. Its listing and tag reading follow this note's
  rules, and give up the topic `obs-component` and the tag form `obs-component/<kind>/<name>/v<version>`.
- Moving to the generic mark: obs's component repositories carry the topic `component`, are named
  after their component, and tag `v<version>`. The adapter `html` keeps living in obs's tree until it
  leaves it, a component of the first kind until then.

Why se_modules for SE, and not a kern component or obs's command reused:

- **It runs before kern exists.** Finding kern is the first step of a fresh clone's start: the clone
  that `sync kern` places is what the `se` binary is built from. A finder inside kern cannot find
  kern; one inside obs cannot find obs.
- **It already does most of it.** se_modules reads pins, resolves origin-relative addresses through
  se_home, reads release tags and locks commits; finding by name is its address step replaced.
- **One rule, two finders.** A shared finder would need a component both SE and obs require; obs
  requires none of SE's, so the rules stay one, here, and each of the two finders is held to them by
  its own tests of this note's cases.

When SE's start moves to the Go core ([go-core.md "Migration"](go-core.md#migration)), the finder
moves with it as one component, as every script does, keeping this note's rules and its tests.

## Finding kern

kern was pinned from its own repository by a relative address, `url = "../kern.git"`
([go-core.md "Pinned from kern's own repository"](go-core.md#pinned-from-kerns-own-repository)),
which resolves to the repository `kern` under origin's owner. Finding kern by its mark gives the same
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

Once the finder lands, `url` leaves `[components.kern]` and the relative address has no other use.

## Steps only the person takes

Adding a topic to a repository is the owner's step, one line each, before SE's start checks its list
([The packages](#the-packages), 3):

- add the topic `component` to the repositories `kern` and `obs`. SE's own repository needs none:
  SE is no component ([method.md](method.md)).

## Open points

- **Installing obs's required components**: obs installs a component only when the person chooses
  it, while a required one in obs's list must be present for obs to build. Whether obs installs a
  required component on its own (at its sync) or SE's start only reports it found but not installed
  is the person's to decide; obs's package waits for it.

## The packages

In order; each is one work issue.

1. **se: the finder** (`components-finder`). `scripts/se_modules.py`: find a name under each
   remote's owner as [Finding a component](#finding-a-component) says, read `[components]` with
   `optional`, refuse `url`, check a found tag against `se.lock`'s commit, resolve the tree
   recursively; `scripts/se_home.py` for remote addresses; `se.toml` `[modules]` to `[components]`;
   README [Modules](../README.md#modules); `tests/test_se_modules.py` on the fake door
   (`tests/fake_git.py`) with a fake host listing. Dropping `url` and renaming the table change the
   format of every `se.toml` SE reads, so it lands as se 6.0.0.
2. **se: the start check** (`start-checks-required-components`). `scripts/se_start.py`
   (`start-components` resolves the tree from what is placed, stops on a required component
   missing, one line for an optional one), `scripts/bootstrap.sh` (the hook shows the stop), README
   [Start and refresh](../README.md#start-and-refresh), `tests/test_se_start.py`.
3. **The person's step**: the topic `component` on `kern` and `obs`, before package 2's release
   reaches a session.
4. **obs: components by the one rule** (obs's repository, follows obs#860). `src/obs/components.py`
   lists and reads by this note's rules and the topic `component`; release tags `v<version>` in a
   repository named after its component; `se.toml` `[components]` with its adapters and styles,
   each required or optional, and no `se`; `spec/design_input/components.md` points here for finding;
   `test/test_components.py`. It waits for the [open point](#open-points).
