// Package host is kern's host: the core's process. It starts in the
// background, detached from whatever started it, stands the bus, says where
// in the standing file, holds the sessions' and the components' leases, runs
// the placed components in processes of their own, and ends when no session
// holds a lease, or when idle. SE's docs/go-core.md ("Lifetime: bound to the
// session") is its design.
package host

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"time"

	"github.com/mb-89/kern/index"
)

// Runtime is the folder, under the checkout, that holds the core's files of
// the moment. It is git-ignored with the rest of .se/.
const Runtime = ".se/.runtime"

// The core's files under Runtime.
const (
	standingFile = "standing.json"
	claimFile    = "start.claim"
	logFile      = "core.log"
)

// Contract is the component contract's version the core speaks, the index's;
// a peer that attaches with another is refused.
const Contract = index.Contract

// Standing is what the standing file says of the running core: its process,
// its bus and the bus's users with their passwords. Only the checkout's
// owner reads it.
type Standing struct {
	Contract int               `json:"contract"`
	Pid      int               `json:"pid"`
	Root     string            `json:"root"`
	Bus      string            `json:"bus"`
	Port     int               `json:"port"`
	Started  time.Time         `json:"started"`
	Users    map[string]string `json:"users"`
}

// ErrNotRunning is what a reader of the standing file meets where no core runs.
var ErrNotRunning = errors.New("no core runs")

// StandingPath is the standing file's path in a checkout.
func StandingPath(root string) string { return filepath.Join(root, Runtime, standingFile) }

// ClaimPath is the claim file's path in a checkout.
func ClaimPath(root string) string { return filepath.Join(root, Runtime, claimFile) }

// LogPath is where a detached core writes what it says.
func LogPath(root string) string { return filepath.Join(root, Runtime, logFile) }

// ReadStanding answers the running core's standing. A file that is missing,
// unreadable, or names a pid that runs nowhere reads as ErrNotRunning.
func ReadStanding(root string) (Standing, error) {
	var s Standing
	data, err := readWhole(StandingPath(root))
	if errors.Is(err, fs.ErrNotExist) {
		return s, ErrNotRunning
	}
	if err != nil {
		return s, fmt.Errorf("%s: %w", StandingPath(root), err)
	}
	if err := json.Unmarshal(data, &s); err != nil || s.Port == 0 || s.Bus == "" {
		return Standing{}, fmt.Errorf("%w: %s names no bus", ErrNotRunning, StandingPath(root))
	}
	if !alive(s.Pid) {
		return Standing{}, fmt.Errorf("%w: %s names pid %d, which runs nowhere", ErrNotRunning, StandingPath(root), s.Pid)
	}
	return s, nil
}

// The looks a read of the standing file takes while the core replaces it:
// Windows refuses to open a file during its rename with a sharing violation.
const (
	readTries = 200
	readPause = time.Millisecond
)

// readWhole reads a file, trying again while an error other than its absence
// stands, since the core's rename of the standing file is over in a moment.
func readWhole(path string) ([]byte, error) {
	data, err := os.ReadFile(path)
	for try := 1; err != nil && !errors.Is(err, fs.ErrNotExist) && try < readTries; try++ {
		time.Sleep(readPause)
		data, err = os.ReadFile(path)
	}
	return data, err
}

// writeStanding writes the standing file whole, readable by its owner alone,
// so a reader never meets half of it.
func writeStanding(root string, s Standing) error {
	dir := filepath.Join(root, Runtime)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	data, err := json.MarshalIndent(s, "", "  ")
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(dir, standingFile+".*")
	if err != nil {
		return err
	}
	if err := tmp.Chmod(0o600); err != nil && !errors.Is(err, errors.ErrUnsupported) {
		_ = tmp.Close()
		_ = os.Remove(tmp.Name())
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		_ = tmp.Close()
		_ = os.Remove(tmp.Name())
		return err
	}
	if err := tmp.Close(); err != nil {
		_ = os.Remove(tmp.Name())
		return err
	}
	// A reader that holds the file open on Windows refuses the rename for a moment.
	err = os.Rename(tmp.Name(), StandingPath(root))
	for try := 1; err != nil && try < readTries; try++ {
		time.Sleep(readPause)
		err = os.Rename(tmp.Name(), StandingPath(root))
	}
	if err != nil {
		_ = os.Remove(tmp.Name())
	}
	return err
}

// dropStanding removes the standing file where it still names pid, so a core
// never removes the file of the core that came after it.
func dropStanding(root string, pid int) {
	var s Standing
	data, err := os.ReadFile(StandingPath(root))
	if err != nil || json.Unmarshal(data, &s) != nil || s.Pid != pid {
		return
	}
	_ = os.Remove(StandingPath(root))
}
