# Development: working on SE

Reader: whoever changes SE's code, at a desk or on a box.

How work lands is [CLAUDE.md](../CLAUDE.md); this file is how SE builds,
checks and debugs itself.

## Two clones

Keep two clones. Run `RUNME.sh` in one that stays on main; `/se update` keeps
it current, and it is the SE every session runs under: the plugin and the
installed `se` in its `src/plugin/bin`. At every session start the plugin
pulls that checkout's `main` as `/se update` does, when it is a clean `main`
(see [spec/cloud.md](cloud.md)). Work on SE in the other clone, on a branch.

A workspace that is itself an SE checkout (its `src/go.mod` declares
`module github.com/mb-89/SE/src`) runs its own `se`. Whenever `se` starts that
workspace's daemon (`/se on`, `/se restart`, or the plugin starting a daemon it
found down) it first builds `se` from the checkout's source into
`.se/.runtime/bin/`, and the daemon runs that build. The session's `/se` words
go to that build too, so a command you add or change in the checkout is offered
and listed by `/se help` after the restart. So: edit the Go code, type
`/se restart`, and the edited daemon and commands are in place, without leaving
the session.

`/se on`, `/se restart` and `/se update` always run in the installed `se`, so
the way to rebuild never depends on the code being edited. If the checkout's
source does not build, the daemon runs the installed `se`, every `/se` word is
answered by it, and the command's answer says so with the build error; fix the
code and `/se restart` again.

Any other workspace runs the installed `se`, and nothing is built there. A
terminal `se` (`se serve` under the debugger among them) runs as it was built
and hands nothing to the checkout's build.

## Adding a command

A command is one file in `src/cmd/se` whose `init` calls `register`; the
fields of `Command` in `src/cmd/se/commands.go` say what it declares. The help,
`/se ui` and the manifests are made from what registered, so nothing else
changes.

## Checks

`sh ./tests/check.sh` is the one definition of green; the pre-push hook and CI
run it, and it names each step it runs. SE's own rules are one file each in
`src/internal/rules`, run by `se rules`. The linters' versions are pinned in
`tests/tools.sh`, and each linter's config gives the reason for anything it
switches off. Only the battery needs them, so check.sh runs
`sh tests/tools.sh install` first for any that is missing or at another
version; a fresh box's first push installs them itself.
`se fmt` installs them the same way, then runs every formatter the battery
checks (`golangci-lint fmt`, `biome check --write`): run it, not each
formatter by hand, when a lint step fails on formatting.

## Debugging the daemon

Open this folder in VS Code and run **se: debug this workspace's daemon**. It
starts `se serve --takeover` under the debugger: the running daemon is asked to
step down, and if the plugin starts another meanwhile, that one is too. Set a
breakpoint in `event` in `src/internal/daemon/server.go`: every event a session in
that workspace raises stops there, and the session waits until you continue.
The plugin finds the debugged daemon through `.se/.runtime/daemon.json`.

The debugger builds `se serve` from the source open in VS Code, so the
breakpoint is in the code that runs. `/se restart` ends the debugged daemon and
puts the checkout's build back in its place.

For a session working in another folder, run
`se stop --workspace <folder>` and then **se: debug another workspace's daemon**.
