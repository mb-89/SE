# SE

SE is a Claude plugin with a Go program behind it. The plugin is the
bridgehead: while SE is on, it posts every event of the session to `se`, the
workspace's daemon, before the event goes on. `se` decides what happens to it;
today it appends the event to the session's log under `.se/.runtime/logs/`.

## Install

    ./RUNME.sh

It needs `go`, `git`, `claude` and `gh`, the GitHub CLI that `se issue` reads
GitHub through. It builds `se`, installs the Go debugger, and installs the
plugin for your user, so every Claude session on this machine has one
command, `/se`, which takes words the way a command line does:

| command | what it does |
|---|---|
| `/se on` | starts this workspace's daemon and forwards every event of the session to it |
| `/se off` | stops forwarding, for this session |
| `/se status` | says whether a daemon answers for this workspace |
| `/se restart` | stops this workspace's daemon and starts it again; in an SE checkout, rebuilt from its source first |
| `/se update` | pulls main into the installed checkout, rebuilds `se`, restarts a running daemon and reloads the plugin |
| `/se issue next` | names the next ready `se` issue, or says that none is ready |
| `/se help`, `/se` | lists these |

On a terminal, `se help` lists every command, those above and the ones a
session is not offered: `se serve`, `se start`, `se stop` and `se issue take`.

The plugin is read from the checkout you ran `RUNME.sh` in.

## SE working on SE

Keep two clones. Run `RUNME.sh` in one that stays on main; `/se update` keeps
it current, and it is the SE every session runs under: the plugin and the
installed `se` in its `plugin/bin`. Work on SE in the other clone, on a branch.

A workspace that is itself an SE checkout (its `go.mod` declares
`module github.com/mb-89/SE`) runs its own `se`. Whenever `se` starts that
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

## Issues

SE's work items are GitHub issues labelled `se`. `se issue next` names the next
one a box may take, and `se issue take` claims it by pushing its branch
`issue-<n>`. The rules for which issue is ready, and how a claim works, live in
[docs/issues.md](docs/issues.md).

## Adding a command

A command is one file in `cmd/se`. Its `init` calls `register` with the
command's name (two words, like `issue next`, make the second a sub-word of
the first), its usage line, a one-line summary, whether a session is
offered it as `/se <name>`, and the function that runs it. The function
answers a `Reply`: the text to show and, for a session, the effects the plugin
applies (switch forwarding on or off, where the daemon now answers, reload the
plugins). The help on both sides is made from what registered, and the plugin
hands every word typed after `/se` to `se --session`, so nothing else changes.

## Debugging the daemon

Open this folder in VS Code and run **se: debug this workspace's daemon**. It
stops the running daemon and starts `se serve` under the debugger. Set a
breakpoint in `event` in `internal/daemon/server.go`: every event a session in
that workspace raises stops there, and the session waits until you continue.
The plugin finds the debugged daemon through `.se/.runtime/daemon.json`.

The debugger builds `se serve` from the source open in VS Code, so the
breakpoint is in the code that runs. `/se restart` ends the debugged daemon and
puts the checkout's build back in its place.

For a session working in another folder, run
`se stop --workspace <folder>` and then **se: debug another workspace's daemon**.

## Cloud boxes

On a box that works on SE itself, set these in the environment's variables:

    CLAUDE_CODE_PLUGIN_DIRS=/home/user/SE/plugin
    SE_DEFAULT=on

`SE_DEFAULT=on` starts every session switched on. The plugin builds `se` from
the checkout the first time it needs it.

## Check

    sh ./tests/check.sh

It runs gofmt, go vet, go test, `claude plugin validate` and
`claude plugin test`. The pre-push hook and CI run the same file.
