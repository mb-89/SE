# Components and modules

## Modules

A repository pulls the parts it builds with (se itself, kern, obs, styles, other repositories) as
**components**, each found by its name on the checkout's remotes and pinned to a commit or a
semantic version range ([docs/components.md](components.md) owns the design).
`scripts/se_modules.py` implements this section; its invocation is in [Commands](running.md#commands).

### `se.toml`

The host, the repository that uses them, lists its components in `se.toml` at its root, by name,
under `[components]` (se 6 renamed it from `[modules]`, which is refused naming the rename):

```toml
[components.obs]
ref = "<40-hex commit SHA>"                  # the pin
path = "skills"                              # optional: the part of the component that is used

[components.style]
version = "^1.4"                             # in place of ref: a semver range of its release tags
optional = true                              # the host works without it; absent: required

[components.kern]
go = "components/go.mod"                     # in place of ref: the version that go.mod requires
```

| Key | Meaning |
|---|---|
| `ref` | the pin, a full commit SHA. Any commit on the component's `main` can be pinned, not only releases; `update` moves it. |
| `version` | in place of `ref`, a semantic version range of the component's release tags `vMAJOR.MINOR.PATCH` ([Project settings](settings.md#project-settings) says how a component releases): `^1.4` (1.4.0 up to 2.0.0), `~1.4.2` (up to 1.5.0), `1.4` (any 1.4.x) or `1.4.2` (exactly). An entry pins one of `ref`, `version` and `go`. |
| `go` | in place of `ref` and `version`, for a Go module: `true` (the root's `go.mod`) or a relative path to a `go.mod`. The pin is the exact version that `go.mod` requires of the module path `<name>` (`require kern v0.14.1`), resolved to the tag `v<version>` and locked in `se.lock` as a range is; a `go.mod` without that require, or a version no owner tags, is refused. `update <name>` refuses and names the `go.mod` line to change instead (`update --all` leaves it as it is). A local checkout's version is its `release.toml` `version`. |
| `optional` | `true` marks a component the host works without: `sync` names one no owner offers in one line and goes on. An entry without it is required, and a required one missing fails, naming its path from the root, the remotes read and the remedy. SE's own `se.toml` declares kern, obs and obs-html so, which every start loads from SE's root ([required components](boot.md#required-components)). |
| `path` | optional relative directory inside the component; without it the whole component is used. |
| `url` | refused: an entry names no address, since a component is found by its name. A machine that needs another place says so in the machine-local file below. |
| `se.lock` | next to `se.toml`, it records, as `[components.<name>]`, the release each `version` range and `go` pin of the tree chose, with its version and commit; `sync` and `update` write it and the repository commits it. |
| Component names | the name of the component's repository, compared without case: 1 to 32 letters, digits and `-`, starting with a letter or digit. Other keys are errors. |
| The component `se` | se itself; its pin is the se the [public check](../AGENTS.md#public-safety) must run: exactly its `ref`, or any se whose `se.toml` version its `version` range admits. |

A common repository lists only components that are public. Work-only components on private hosts
are listed the same way, in a work repository that uses the common ones; a common repository never
names them.

#### Finding a component

`sync` and `update` find each name as [docs/components.md "Finding a component"](components.md#finding-a-component)
says, reading only the checkout's own Git configuration:

- The remotes: `origin` first, then the others in the order Git lists them; each remote's host
  and owner come from its address (`scripts/se_home.py`); a local path offers nothing.
- The mark: on `github.com` the owner's repositories with the topic `component` are listed once
  per run, with the login of `GH_TOKEN` or `GITHUB_TOKEN` where one is set. The repository named
  like the component is reached as its remote is, with its name in place of the remote's.
- An owner the host cannot list is one line, and finding goes on with the next owner. On a host
  SE lists nothing of, or where the listing cannot be read, the repository beside the remote is
  read directly, its mark unchecked, in one line. `SE_COMPONENT_LISTING=off` does so everywhere.
- The releases: its `v` tags, read without fetching objects (`git ls-remote --tags`); the first
  owner that offers a release the pin admits wins, and its highest admitted release is taken.

A clone already at its locked commit is used without asking any remote. A found release whose tag
points to another commit than `se.lock` records is refused, naming both commits and
`se_modules.py update <name>`, so a stand-in never replaces a locked component silently.

Another owner's components join by adding any one of that owner's repositories as a remote; a fork
named like a component under such an owner stands in for it where the pin admits its release.

#### The tree

Resolving is recursive: each placed component's own `se.toml` `[components]`, read from its
release (a local checkout's working tree), is resolved the same way, and every component of the
tree is placed in the root's `.se/modules/<name>`. A release whose `se.toml` lists no
`[components]` lists none.

- One version per name: a name the tree reaches twice is one component, and each host's pin must
  admit its release; where they admit a common one the newest is taken, else `sync` fails naming
  both paths and both pins.
- A name already on the path is that component: an entry that names a host above it on the path,
  the root included, is that host itself, and its pin is checked against that host's version, not
  resolved again.
- The runtimes: each component's `se.toml` `[runtimes]` names the runtimes it needs with a range
  of their versions (`python = "^3.12"`). `sync` and the start collect them over the tree, get
  what the machine lacks through the root's `RUNME.conf` and stop before any component runs where
  one is still missing ([docs/components.md "Runtimes"](components.md#runtimes)).
