package main

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"

	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/disk"
	sehttp "github.com/mb-89/SE/src/internal/io/http"
	"github.com/mb-89/SE/src/internal/io/proc"

	"github.com/mb-89/SE/src/internal/daemon"
	"github.com/mb-89/SE/src/internal/update"
)

// A workspace that is an SE checkout runs its own se: every daemon start builds
// se from the checkout's source into .se/.runtime/bin and starts that, and the
// session's /se words go to it, so a command added there is offered after
// /se restart. Where the source does not build, the installed se stands in.

// handedOver marks an se run by another se; it hands nothing over again.
const handedOver = "SE_HANDED_OVER"

// handsOver runs the se built from the workspace's checkout on d with these args,
// when there is one, and answers its exit code. handed is false where this se
// answers itself: not a checkout, nothing built, or the build would not run.
func handsOver(d disk.Disk, procs proc.Procs, workspace string, args []string, stdout, stderr io.Writer) (code int, handed bool) {
	if os.Getenv(handedOver) != "" {
		return 0, false
	}
	root, err := filepath.Abs(workspace)
	if err != nil || !update.IsCheckout(d, root) {
		return 0, false
	}
	bin := daemon.Paths{Workspace: root, Disk: d}.Bin()
	if there, err := d.Exists(bin); err != nil || !there {
		return 0, false
	}
	err = procs.Run(proc.Cmd{Name: bin, Args: args, Stdout: stdout, Stderr: stderr, Env: append(os.Environ(), handedOver+"=1")})
	return proc.ExitCode(err)
}

// daemonExe is the se the workspace's daemon runs, built first where the
// workspace is an SE checkout. note says which se that is, and why, where it
// is not simply the installed one.
func daemonExe(procs proc.Procs, p daemon.Paths) (exe, note string, err error) {
	installed, err := executable()
	if err != nil {
		return "", "", err
	}
	if !update.IsCheckout(p.Disk, p.Workspace) {
		return installed, "", nil
	}
	if err := daemon.Prepare(p); err != nil {
		return "", "", err
	}
	if err := update.Build(p.Disk, procs, p.Workspace, p.Bin()); err != nil {
		// A build left from before would answer the session's /se words.
		withdraw(p.Disk, p.Bin())
		return installed, fmt.Sprintf("This checkout's se does not build, so the daemon runs the installed se (%s):\n%v", installed, err), nil
	}
	return p.Bin(), "The daemon runs se built from this checkout.", nil
}

// startDaemon answers the running daemon, or starts one with daemonExe. Starts
// in every process run one at a time.
func startDaemon(procs proc.Procs, p daemon.Paths, clk clock.Clock, net sehttp.Net) (daemon.Endpoint, string, error) {
	if ep, ok := daemon.Healthy(p, net); ok {
		return ep, "", nil
	}
	held, err := starting(p, clk)
	if err != nil {
		return daemon.Endpoint{}, "", err
	}
	defer held.Close()
	return startsDaemon(procs, p, clk, net)
}

// startsDaemon is startDaemon for a caller that holds the start lock.
func startsDaemon(procs proc.Procs, p daemon.Paths, clk clock.Clock, net sehttp.Net) (daemon.Endpoint, string, error) {
	// Another start may have answered while this one waited for the lock.
	if ep, ok := daemon.Healthy(p, net); ok {
		return ep, "", nil
	}
	if err := tries(p, clk); err != nil {
		return daemon.Endpoint{}, "", err
	}
	exe, note, err := daemonExe(procs, p)
	if err != nil {
		return daemon.Endpoint{}, "", err
	}
	ep, err := daemon.Start(procs, p, exe, startWait, clk, net)
	return ep, note, err
}

// withdraw removes a binary, or where it runs and cannot go, renames it away.
func withdraw(d disk.Disk, path string) {
	if err := d.Remove(path); err == nil || errors.Is(err, fs.ErrNotExist) {
		return
	}
	_ = d.Remove(path + ".old")
	_ = d.Rename(path, path+".old")
}
