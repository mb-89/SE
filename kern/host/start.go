package host

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"time"
)

// ClaimStale is how long a claim stands without a core coming up: past it,
// the claim's starter is taken to have failed, and the next start claims anew.
const ClaimStale = 10 * time.Second

// Started is what a start found or did.
type Started int

const (
	// Running: a core already runs; the start did nothing.
	Running Started = iota
	// Spawned: this start claimed it and spawned the core, which comes up on its own.
	Spawned
	// Starting: another caller's claim stands; its core comes up.
	Starting
)

func (s Started) String() string {
	switch s {
	case Running:
		return "running"
	case Spawned:
		return "started"
	default:
		return "starting"
	}
}

// Start makes sure a core runs in the checkout at root, and returns at once:
// where none runs and no other caller's claim stands, it claims the start and
// spawns `<bin> serve --root <root> <args>` detached, writing what it says to
// the core's log. The core removes the claim once its standing file is
// written; a claim that outlives ClaimStale is taken over. From quackitect
// v5's start and claim, without v5's wait for the core: a hook's start costs
// the spawn alone.
func Start(clock Clock, root, bin string, args ...string) (Started, error) {
	if _, err := ReadStanding(root); err == nil {
		return Running, nil
	}
	ok, err := claim(clock, root)
	if err != nil {
		return 0, err
	}
	if !ok {
		return Starting, nil
	}
	if err := spawn(root, bin, args); err != nil {
		_ = os.Remove(ClaimPath(root))
		return 0, err
	}
	return Spawned, nil
}

// claim takes the start where no live claim stands. Two callers racing a
// start see one claim: the file is created exclusively.
func claim(clock Clock, root string) (bool, error) {
	path := ClaimPath(root)
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return false, fmt.Errorf("kern start: %w", err)
	}
	if st, err := os.Stat(path); err == nil && clock.Now().Sub(st.ModTime()) > ClaimStale {
		_ = os.Remove(path)
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if errors.Is(err, fs.ErrExist) {
		return false, nil
	}
	if err != nil {
		return false, fmt.Errorf("kern start: claim %s: %w", path, err)
	}
	_, _ = fmt.Fprintf(f, "%d\n", os.Getpid())
	return true, f.Close()
}

func spawn(root, bin string, args []string) error {
	log, err := os.OpenFile(LogPath(root), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return fmt.Errorf("kern start: %w", err)
	}
	defer log.Close()
	run := detached(exec.Command(bin, append([]string{"serve", "--root", root}, args...)...))
	run.Dir = root
	run.Env = os.Environ()
	run.Stdout, run.Stderr = log, log
	if err := run.Start(); err != nil {
		return fmt.Errorf("kern start: spawn %s: %w", bin, err)
	}
	// The core, or on Windows its starter, outlives nothing of this process.
	return run.Process.Release()
}
