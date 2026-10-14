// Package daemon is SE's workspace program: one process per workspace that the
// plugin's bridgehead forwards session events to, and that hosts the index.
package daemon

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"time"
)

// ProtocolVersion is what the bridgehead and the daemon agree on.
const ProtocolVersion = 1

// Endpoint is daemon.json: where a running daemon answers, and the token it takes.
type Endpoint struct {
	PID             int       `json:"pid"`
	Address         string    `json:"address"`
	Token           string    `json:"token"`
	InstanceID      string    `json:"instanceId"`
	ProtocolVersion int       `json:"protocolVersion"`
	StartedAt       time.Time `json:"startedAt"`
}

// Paths names the files a workspace's runtime folder holds.
type Paths struct{ Workspace string }

func (p Paths) Runtime() string   { return filepath.Join(p.Workspace, ".se", ".runtime") }
func (p Paths) Endpoint() string  { return filepath.Join(p.Runtime(), "daemon.json") }
func (p Paths) Lock() string      { return filepath.Join(p.Runtime(), "daemon.lock") }
func (p Paths) Logs() string      { return filepath.Join(p.Runtime(), "logs") }
func (p Paths) DaemonLog() string { return filepath.Join(p.Logs(), "daemon.log") }

// Bin is where se built from a workspace that is an SE checkout lands.
func (p Paths) Bin() string {
	if runtime.GOOS == "windows" {
		return filepath.Join(p.Runtime(), "bin", "se.exe")
	}
	return filepath.Join(p.Runtime(), "bin", "se")
}

// Prepare makes the runtime folder and the file that keeps it out of git.
func Prepare(p Paths) error {
	if err := os.MkdirAll(p.Logs(), 0o755); err != nil {
		return err
	}
	ignore := filepath.Join(p.Runtime(), ".gitignore")
	if _, err := os.Stat(ignore); errors.Is(err, os.ErrNotExist) {
		return os.WriteFile(ignore, []byte("*\n"), 0o644)
	}
	return nil
}

// WriteEndpoint publishes daemon.json whole or not at all.
func WriteEndpoint(path string, ep Endpoint) error {
	data, err := json.MarshalIndent(ep, "", "  ")
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), "daemon-*.json")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if _, err := tmp.Write(append(data, '\n')); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), path)
}

// ReadEndpoint reads daemon.json.
func ReadEndpoint(path string) (Endpoint, error) {
	var ep Endpoint
	data, err := os.ReadFile(path)
	if err != nil {
		return ep, err
	}
	err = json.Unmarshal(data, &ep)
	return ep, err
}
