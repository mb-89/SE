package daemon

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
)

// direct never goes through a proxy: the daemon answers on loopback alone.
var direct = &http.Client{Transport: &http.Transport{Proxy: nil}, Timeout: 2 * time.Second}

// Healthy answers the endpoint of a daemon that runs and answers for this workspace.
func Healthy(paths Paths) (Endpoint, bool) {
	ep, err := ReadEndpoint(paths.Endpoint())
	if err != nil {
		return ep, false
	}
	var said struct {
		ProtocolVersion int    `json:"protocolVersion"`
		InstanceID      string `json:"instanceId"`
	}
	if err := call(ep, http.MethodGet, "/health", &said); err != nil {
		return ep, false
	}
	return ep, said.ProtocolVersion == ProtocolVersion && said.InstanceID == ep.InstanceID
}

// Start answers the running daemon, or starts exe as the workspace's daemon and waits for it by clk.
func Start(paths Paths, exe string, wait time.Duration, clk clock.Clock) (Endpoint, error) {
	if ep, ok := Healthy(paths); ok {
		return ep, nil
	}
	if err := Prepare(paths); err != nil {
		return Endpoint{}, err
	}
	out, err := os.OpenFile(paths.DaemonLog(), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
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
		if ep, ok := Healthy(paths); ok {
			return ep, nil
		}
		select {
		case err := <-exited:
			// A daemon that lost the lock race leaves the winner answering.
			if ep, ok := Healthy(paths); ok {
				return ep, nil
			}
			return Endpoint{}, fmt.Errorf("the daemon exited at start (%v); see %s", err, paths.DaemonLog())
		case <-clk.After(50 * time.Millisecond):
		}
	}
	return Endpoint{}, fmt.Errorf("the daemon did not answer within %s; see %s", wait, paths.DaemonLog())
}

// Stop asks the workspace's daemon to end and waits by clk until it has withdrawn.
func Stop(paths Paths, wait time.Duration, clk clock.Clock) error {
	ep, ok := Healthy(paths)
	if !ok {
		return nil
	}
	if err := call(ep, http.MethodPost, "/shutdown", nil); err != nil {
		return err
	}
	deadline := clk.Now().Add(wait)
	for clk.Now().Before(deadline) {
		if _, err := os.Stat(paths.Endpoint()); errors.Is(err, os.ErrNotExist) {
			return nil
		}
		clk.Sleep(50 * time.Millisecond)
	}
	return fmt.Errorf("the daemon did not stop within %s", wait)
}

func call(ep Endpoint, method, path string, into any) error {
	req, err := http.NewRequest(method, "http://"+ep.Address+path, nil)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+ep.Token)
	resp, err := direct.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("%s %s: status %d", method, path, resp.StatusCode)
	}
	if into == nil {
		return nil
	}
	return json.NewDecoder(resp.Body).Decode(into)
}
