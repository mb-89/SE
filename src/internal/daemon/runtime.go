// Package daemon is SE's workspace program: one process per workspace that the
// plugin's bridgehead forwards session events to, and that writes the log.
package daemon

import (
	"encoding/json"
	"path/filepath"
	"runtime"
	"time"

	"github.com/mb-89/SE/src/internal/io/disk"
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

// Paths names the files a workspace's runtime folder holds, and the disk they are on.
type Paths struct {
	Workspace string
	Disk      disk.Disk
}

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
	if err := p.Disk.MkdirAll(p.Logs()); err != nil {
		return err
	}
	ignore := filepath.Join(p.Runtime(), ".gitignore")
	there, err := p.Disk.Exists(ignore)
	if err != nil || there {
		return err
	}
	return p.Disk.WriteFile(ignore, []byte("*\n"))
}

// WriteEndpoint publishes the workspace's daemon.json whole or not at all.
func WriteEndpoint(p Paths, ep Endpoint) error {
	data, err := json.MarshalIndent(ep, "", "  ")
	if err != nil {
		return err
	}
	return p.Disk.Replace(p.Endpoint(), append(data, '\n'))
}

// ReadEndpoint reads the workspace's daemon.json.
func ReadEndpoint(p Paths) (Endpoint, error) {
	var ep Endpoint
	data, err := p.Disk.ReadFile(p.Endpoint())
	if err != nil {
		return ep, err
	}
	err = json.Unmarshal(data, &ep)
	return ep, err
}
