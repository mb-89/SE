// Package origin is SE's origin component: an I/O component whose one
// outside thing is the checkout's git, writing origin's branches with the
// committer time of each tip, as the checkout last fetched or pushed them.
// The fleet component reads it for the rules on branches (no branch, quiet
// branch, stray branch). It reads local refs only and fetches nothing: the
// Python fleet-check fetches before it reads.
package origin

import (
	"context"
	"encoding/json"
	"strings"
	"sync"
	"time"

	"github.com/mb-89/kern/git"
	"github.com/mb-89/kern/index"
)

// Name is the component's name, which the wiring's instances name.
const Name = "origin"

var branchesOut = index.Output("branches", map[string]time.Time{}, "Origin's branches, each with the committer time of its tip, from refs/remotes/origin.")

// The host's events after which origin's refs may have moved and are read again.
var events = map[string]bool{"SessionStart": true, "UserPromptSubmit": true, "Stop": true, "SubagentStop": true}

// Read answers origin's branches in the checkout at dir; a test replaces it.
var Read = func(dir string) (map[string]time.Time, error) {
	out, err := git.Run(context.Background(), dir, "for-each-ref",
		"--format=%(refname:lstrip=3)%09%(committerdate:iso-strict)", "refs/remotes/origin/")
	if err != nil {
		return nil, err // the door's error names the command and dir
	}
	found := map[string]time.Time{}
	for _, line := range strings.Split(out, "\n") {
		name, when, _ := strings.Cut(line, "\t")
		if name == "" || name == "HEAD" || when == "" {
			continue
		}
		if t, err := time.Parse(time.RFC3339, when); err == nil {
			found[name] = t.UTC()
		}
	}
	return found, nil
}

type state struct {
	mu     sync.Mutex
	dir    string
	commit index.Commit
}

var s state

// refresh reads the branches and commits them.
func refresh() error {
	s.mu.Lock()
	dir, commit := s.dir, s.commit
	s.mu.Unlock()
	if commit == nil {
		return nil
	}
	b, err := Read(dir)
	if err != nil {
		return err
	}
	return commit(branchesOut.Set(b))
}

// Component is the component a binary carries.
var Component = index.Declare(Name, "Origin's branches and the time of each tip, read from the checkout's git.",
	index.IO(),
	index.Config("dir", ".", "The checkout whose refs/remotes/origin it reads; a detached core runs in its root."),
	branchesOut,
	index.Inlet(func(_ string, read index.Reader, commit index.Commit) error {
		dir, _ := read(index.ConfigPrefix + "dir").(string)
		s.mu.Lock()
		s.dir, s.commit = dir, commit
		s.mu.Unlock()
		return refresh()
	}),
	index.Hears(func(_, event string, payload []byte) error {
		if event == "PostToolUse" {
			var p struct {
				Tool string `json:"tool_name"`
			}
			if json.Unmarshal(payload, &p) != nil || p.Tool != "Bash" {
				return nil
			}
		} else if !events[event] {
			return nil
		}
		return refresh()
	}),
)

func init() { index.Register(Component) }
