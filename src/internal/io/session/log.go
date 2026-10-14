package session

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
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

// Folder answers the log folder dir: each session's log is <session>.jsonl in it.
func Folder(dir string) Log { return &folder{dir: dir} }

type folder struct {
	dir string
	mu  sync.Mutex
}

func (f *folder) Append(session string, line []byte) error {
	if !Named(session) {
		return fmt.Errorf("no session is named %q", session)
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	file, err := os.OpenFile(f.path(session), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	if _, err := file.Write(append(append([]byte{}, line...), '\n')); err != nil {
		file.Close()
		return err
	}
	return file.Close()
}

func (f *folder) Read(session string) ([]byte, error) {
	if !Named(session) {
		return nil, fmt.Errorf("no session is named %q", session)
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	b, err := os.ReadFile(f.path(session))
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	return b, err
}

func (f *folder) path(session string) string { return filepath.Join(f.dir, session+".jsonl") }
