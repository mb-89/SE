# SE

SE is a Claude plugin with a Go program behind it. The plugin is the
bridgehead: while SE is on, it posts every event of the session to `se`, the
workspace's daemon, before the event goes on. `se` decides what happens to it;
today it appends the event to the session's log under `.se/.runtime/logs/`.

## Install

    ./RUNME.sh

That builds `se`, installs the Go debugger, and installs the plugin for your
user, so every Claude session on this machine has these commands:

| command | what it does |
|---|---|
| `/se-on` | starts this workspace's daemon and forwards every event to it |
| `/se-off` | stops forwarding, for this session |
| `/se-update` | pulls main into the installed checkout, rebuilds `se`, restarts the daemon and reloads the plugin |

The plugin is read from the checkout you ran `RUNME.sh` in.

## SE working on SE

Keep two clones. Run `RUNME.sh` in one that stays on main; `/se-update` keeps
it current, and it is the SE every session runs under. Work on SE in the other
clone, on a branch. That way a session never runs the code it is editing.

## Debugging the daemon

Open this folder in VS Code and run **se: debug this workspace's daemon**. It
stops the running daemon and starts `se serve` under the debugger. Set a
breakpoint in `event` in `internal/daemon/server.go`: every event a session in
that workspace raises stops there, and the session waits until you continue.
The plugin finds the debugged daemon through `.se/.runtime/daemon.json`.

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
