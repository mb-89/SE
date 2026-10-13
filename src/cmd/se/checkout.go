package main

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"

	"github.com/mb-89/SE/src/internal/daemon"
	"github.com/mb-89/SE/src/internal/update"
)

// A workspace that is an SE checkout runs its own se: every daemon start builds
// se from the checkout's source into .se/.runtime/bin and starts that, and the
// session's /se words go to it, so a command added there is offered after
// /se restart. Where the source does not build, the installed se stands in.

// handedOver marks an se run by another se; it hands nothing over again.
const handedOver = "SE_HANDED_OVER"

// handsOver runs the se built from the workspace's checkout with these args,
// when there is one, and answers its exit code. handed is false where this se
// answers itself: not a checkout, nothing built, or the build would not run.
func handsOver(workspace string, args []string, stdout, stderr io.Writer) (code int, handed bool) {
	if os.Getenv(handedOver) != "" {
		return 0, false
	}
	root, err := filepath.Abs(workspace)
	if err != nil || !update.IsCheckout(root) {
		return 0, false
	}
	bin := daemon.Paths{Workspace: root}.Bin()
	if _, err := os.Stat(bin); err != nil {
		return 0, false
	}
	cmd := exec.Command(bin, args...)
	cmd.Stdout, cmd.Stderr = stdout, stderr
	cmd.Env = append(os.Environ(), handedOver+"=1")
	err = cmd.Run()
	var exit *exec.ExitError
	if errors.As(err, &exit) {
		return exit.ExitCode(), true
	}
	return 0, err == nil
}

// daemonExe is the se the workspace's daemon runs, built first where the
// workspace is an SE checkout. note says which se that is, and why, where it
// is not simply the installed one.
func daemonExe(p daemon.Paths) (exe, note string, err error) {
	installed, err := executable()
	if err != nil {
		return "", "", err
	}
	if !update.IsCheckout(p.Workspace) {
		return installed, "", nil
	}
	if err := daemon.Prepare(p); err != nil {
		return "", "", err
	}
	if err := update.Build(p.Workspace, p.Bin()); err != nil {
		// A build left from before would answer the session's /se words.
		withdraw(p.Bin())
		return installed, fmt.Sprintf("This checkout's se does not build, so the daemon runs the installed se (%s):\n%v", installed, err), nil
	}
	return p.Bin(), "The daemon runs se built from this checkout.", nil
}

// startDaemon answers the running daemon, or starts one with daemonExe.
func startDaemon(p daemon.Paths) (daemon.Endpoint, string, error) {
	if ep, ok := daemon.Healthy(p); ok {
		return ep, "", nil
	}
	exe, note, err := daemonExe(p)
	if err != nil {
		return daemon.Endpoint{}, "", err
	}
	ep, err := daemon.Start(p, exe, startWait)
	return ep, note, err
}

// withdraw removes a binary, or where it runs and cannot go, renames it away.
func withdraw(path string) {
	if err := os.Remove(path); err == nil || errors.Is(err, os.ErrNotExist) {
		return
	}
	os.Remove(path + ".old")
	_ = os.Rename(path, path+".old")
}
