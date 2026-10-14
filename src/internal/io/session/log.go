package session

import (
	"errors"
	"fmt"
	"io/fs"
	"path/filepath"
	"sync"

	"github.com/mb-89/SE/src/internal/io/disk"
)

// Log is what SE asks of the session log folder: one log per session, which
// only grows.
type Log interface {
	// Append adds one line to the session's log; a session name that is not
	// Named is refused.
	Append(session string, line []byte) error
	// Read answers the session's log as it stands; a session never appended reads empty.
	Read(session string) ([]byte, error)
}

// Folder answers the log folder dir on d: each session's log is <session>.jsonl in it.
func Folder(d disk.Disk, dir string) Log { return &folder{disk: d, dir: dir} }

type folder struct {
	disk disk.Disk
	dir  string
	mu   sync.Mutex
}

func (f *folder) Append(session string, line []byte) error {
	if !Named(session) {
		return fmt.Errorf("no session is named %q", session)
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	w, err := f.disk.Append(f.path(session))
	if err != nil {
		return err
	}
	if _, err := w.Write(append(append([]byte{}, line...), '\n')); err != nil {
		w.Close()
		return err
	}
	return w.Close()
}

func (f *folder) Read(session string) ([]byte, error) {
	if !Named(session) {
		return nil, fmt.Errorf("no session is named %q", session)
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	b, err := f.disk.ReadFile(f.path(session))
	if errors.Is(err, fs.ErrNotExist) {
		return nil, nil
	}
	return b, err
}

func (f *folder) path(session string) string { return filepath.Join(f.dir, session+".jsonl") }
