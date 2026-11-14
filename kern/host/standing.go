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
	"net"
	neturl "net/url"
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

// Standing is what the standing file says of the running core: its process
// with its start mark (procMark), the boot it runs in (Boot) and when it
// started, its bus and the bus's users with their passwords. Only the
// checkout's owner reads it.
type Standing struct {
	Contract int               `json:"contract"`
	Pid      int               `json:"pid"`
	Proc     string            `json:"proc"`
	Boot     string            `json:"boot"`
	Root     string            `json:"root"`
	Bus      string            `json:"bus"`
	Port     int               `json:"port"`
	Started  time.Time         `json:"started"`
	Users    map[string]string `json:"users"`
}

// ErrNotRunning is what a reader of the standing file meets where no core runs.
var ErrNotRunning = errors.New("no core runs")

// ErrVanished is ErrNotRunning where the standing file names a pid that runs
// nowhere: the core ended without its end, killed or crashed (TakeVanished).
var ErrVanished = fmt.Errorf("%w: its process ended without its end", ErrNotRunning)

// ErrReused is ErrVanished where the standing file names a pid that runs as
// another process than its core (its start mark differs), or whose bus
// accepts no connection: the core is gone, and its pid is not reaped yet or
// is another process's now. A machine restarted with the checkout's files
// kept, as a cloud environment restored from its snapshot is, gives its
// processes the pids of the last boot, the start's own among them, so the
// file of a core of that boot names a live process that is no core; a
// restored snapshot may keep the boot id too (Boot), so the start mark, not
// the boot, tells them apart.
var ErrReused = fmt.Errorf("%w: its pid runs as another process, or its bus is gone", ErrVanished)

// ErrEarlierBoot is ErrNotRunning where the standing file names a core of an
// earlier boot (Boot): the machine restarted with the checkout's files kept,
// and that core ended with its boot, which is no news to this boot's session.
var ErrEarlierBoot = fmt.Errorf("%w: it names a core of an earlier boot", ErrNotRunning)

// BusWait bounds the look at the standing file's bus: a running core's
// listener accepts on the loopback at once, whatever the core is busy with.
const BusWait = time.Second

// StandingPath is the standing file's path in a checkout.
func StandingPath(root string) string { return filepath.Join(root, Runtime, standingFile) }

// ClaimPath is the claim file's path in a checkout.
func ClaimPath(root string) string { return filepath.Join(root, Runtime, claimFile) }

// LogPath is where a detached core writes what it says.
func LogPath(root string) string { return filepath.Join(root, Runtime, logFile) }

// ReadStanding answers the running core's standing. A file that is missing,
// unreadable, names an earlier boot (ErrEarlierBoot), names a pid that runs
// nowhere, names a pid that another process holds now, or names a bus that
// accepts no connection reads as ErrNotRunning (judge).
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
	if err := judge(s); err != nil {
		return Standing{}, fmt.Errorf("%s %w", StandingPath(root), err)
	}
	return s, nil
}

// judge says why the standing s names no running core, nil where it names
// one: its boot is an earlier one (ErrEarlierBoot), its pid runs nowhere
// (ErrVanished), its pid runs as another process than its core, by the start
// mark s keeps, or its bus accepts nothing (ErrReused). A file that keeps no
// mark, or a platform that names none, leaves the bus to tell a reused pid.
func judge(s Standing) error {
	if earlierBoot(s.Boot) {
		return fmt.Errorf("names boot %s, and this is boot %s: %w", s.Boot, Boot(), ErrEarlierBoot)
	}
	if !alive(s.Pid) {
		return fmt.Errorf("names pid %d, which runs nowhere: %w", s.Pid, ErrVanished)
	}
	if now := procMark(s.Pid); s.Proc != "" && now != "" && now != s.Proc {
		return fmt.Errorf("names pid %d of start %s, and that pid runs a process of start %s: %w", s.Pid, s.Proc, now, ErrReused)
	}
	if !accepts(s.Bus) {
		return fmt.Errorf("names pid %d, which runs, and its bus %s accepts no connection: %w", s.Pid, s.Bus, ErrReused)
	}
	return nil
}

// accepts says whether the bus at url takes a connection within BusWait.
func accepts(url string) bool {
	u, err := neturl.Parse(url)
	if err != nil || u.Host == "" {
		return false
	}
	conn, err := net.DialTimeout("tcp", u.Host, BusWait)
	if err != nil {
		return false
	}
	_ = conn.Close()
	return true
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
