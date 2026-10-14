package daemon

import (
	"fmt"
	"os/exec"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
	sehttp "github.com/mb-89/SE/src/internal/io/http"
)

// Healthy answers the endpoint of a daemon that runs and answers for this workspace.
func Healthy(paths Paths, net sehttp.Net) (Endpoint, bool) {
	ep, err := ReadEndpoint(paths)
	if err != nil {
		return ep, false
	}
	said, err := net.Health(ep.Address, ep.Token)
	if err != nil {
		return ep, false
	}
	return ep, said.ProtocolVersion == ProtocolVersion && said.InstanceID == ep.InstanceID
}

// Start answers the running daemon, or starts exe as the workspace's daemon and waits for it by clk.
func Start(paths Paths, exe string, wait time.Duration, clk clock.Clock, net sehttp.Net) (Endpoint, error) {
	if ep, ok := Healthy(paths, net); ok {
		return ep, nil
	}
	if err := Prepare(paths); err != nil {
		return Endpoint{}, err
	}
	// The real disk answers the log as a file, which the daemon writes itself.
	out, err := paths.Disk.Append(paths.DaemonLog())
	if err != nil {
		return Endpoint{}, err
	}
	defer out.Close()
	cmd := exec.Command(exe, "serve", "--workspace", paths.Workspace)
	cmd.Stdout, cmd.Stderr = out, out
	cmd.SysProcAttr = detached()
	if err := cmd.Start(); err != nil {
		return Endpoint{}, err
	}
	exited := make(chan error, 1)
	go func() { exited <- cmd.Wait() }()
	deadline := clk.Now().Add(wait)
	for clk.Now().Before(deadline) {
		if ep, ok := Healthy(paths, net); ok {
			return ep, nil
		}
		select {
		case err := <-exited:
			// A daemon that lost the lock race leaves the winner answering.
			if ep, ok := Healthy(paths, net); ok {
				return ep, nil
			}
			return Endpoint{}, fmt.Errorf("the daemon exited at start (%v); see %s", err, paths.DaemonLog())
		case <-clk.After(50 * time.Millisecond):
		}
	}
	return Endpoint{}, fmt.Errorf("the daemon did not answer within %s; see %s", wait, paths.DaemonLog())
}

// Stop asks the workspace's daemon to end and waits by clk until it has withdrawn.
func Stop(paths Paths, wait time.Duration, clk clock.Clock, net sehttp.Net) error {
	ep, ok := Healthy(paths, net)
	if !ok {
		return nil
	}
	if err := net.Shutdown(ep.Address, ep.Token); err != nil {
		return err
	}
	deadline := clk.Now().Add(wait)
	for clk.Now().Before(deadline) {
		if there, err := paths.Disk.Exists(paths.Endpoint()); err == nil && !there {
			return nil
		}
		clk.Sleep(50 * time.Millisecond)
	}
	return fmt.Errorf("the daemon did not stop within %s", wait)
}
