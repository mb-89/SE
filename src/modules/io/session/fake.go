package session

import (
	"fmt"
	"sync"
)

// Fake is a log folder held in memory: it keeps each session's lines as the
// real folder does, and touches no disk.
type Fake struct {
	mu   sync.Mutex
	logs map[string][]byte
}

// NewFake answers an empty fake log folder.
func NewFake() *Fake { return &Fake{logs: map[string][]byte{}} }

// Append adds one line to the session's log.
func (f *Fake) Append(session string, line []byte) error {
	if !Named(session) {
		return fmt.Errorf("no session is named %q", session)
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	f.logs[session] = append(append(f.logs[session], line...), '\n')
	return nil
}

// Read answers the session's log as it stands.
func (f *Fake) Read(session string) ([]byte, error) {
	if !Named(session) {
		return nil, fmt.Errorf("no session is named %q", session)
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]byte(nil), f.logs[session]...), nil
}
