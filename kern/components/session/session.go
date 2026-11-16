// Package session is kern's session record: an I/O component that hears
// every event the host hands the core and appends it, one JSON line each, to
// a file per session. It is off by default: it runs only where a wiring
// holds an enabled instance of it, as a checkout's own ignored overlay does.
// It declares no output, verb or command, so nothing reads the record over
// the bus and no tool prints it. README.md beside this file is its contract.
package session

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"

	"kern/index"
)

// Name is the component's name, which the wiring's instances name.
const Name = "session"

// Dir is the folder the record is written under, relative to the core's
// working directory, which the start makes the checkout's root.
const Dir = ".se/.runtime/sessions"

// Unknown is the file name of the events whose session id is missing or no
// safe file name.
const Unknown = "unknown"

// The config keys' built-in values.
const (
	MaxBytes = 1 << 20 // per file
	Keep     = 20      // session files
)

// Options are what the component reaches the outside with; each has a
// default, and a test replaces them.
type Options struct {
	// Dir is the folder the session files lie in; Dir (the constant) where empty.
	Dir string
	// Now is the clock each line's time comes from.
	Now func() time.Time
}

// Session is the component and its state: one per core.
type Session struct {
	// Component is what the index, the wiring and the catalog see.
	Component *index.Component
	o         Options

	mu       sync.Mutex
	max      map[string]int64 // each started instance's max-bytes
	pending  error            // a failure not yet returned to the core
	reported bool             // a failure was returned to the core
}

// New makes the component with its outside reached through o.
func New(o Options) *Session {
	if o.Dir == "" {
		o.Dir = Dir
	}
	if o.Now == nil {
		o.Now = time.Now
	}
	s := &Session{o: o, max: map[string]int64{}}
	s.Component = index.Declare(Name, "Appends every event the host hands the core, one JSON line each, to a file per session under "+Dir+".",
		index.IO(),
		index.Config("max-bytes", MaxBytes, "The size a session file may reach: a line that would take it past is written short, without its payload."),
		index.Config("keep", Keep, "How many session files the start keeps, the newest by modification time; it removes the others."),
		index.Inlet(s.start),
		index.Hears(s.hear),
	)
	return s
}

// Component is the component a binary carries; importing this package
// registers it, and only a wiring's enabled instance runs it.
var Component = New(Options{})

func init() { index.Register(Component.Component) }

// start reads the instance's config and prunes the folder to keep files.
func (s *Session) start(instance string, read index.Reader, _ index.Commit) error {
	positive := func(key string) (int, error) {
		n, ok := read(index.ConfigPrefix + key).(int)
		if !ok || n < 1 {
			return 0, fmt.Errorf("config %s: %v is below 1", key, read(index.ConfigPrefix+key))
		}
		return n, nil
	}
	maxBytes, err := positive("max-bytes")
	if err != nil {
		return err
	}
	keep, err := positive("keep")
	if err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.max[instance] = int64(maxBytes)
	if err := prune(s.o.Dir, keep); err != nil && s.pending == nil {
		s.pending = err
	}
	return nil
}

// prune removes every *.jsonl file of dir but the keep newest, by
// modification time. A folder that is missing, or no folder, has none.
func prune(dir string, keep int) error {
	entries, err := os.ReadDir(dir)
	if err != nil {
		if fi, serr := os.Stat(dir); serr != nil || !fi.IsDir() {
			return nil
		}
		return fmt.Errorf("session: read %s: %w", dir, err)
	}
	type file struct {
		name string
		mod  time.Time
	}
	var files []file
	for _, e := range entries {
		if !e.Type().IsRegular() || !strings.HasSuffix(e.Name(), ".jsonl") {
			continue
		}
		info, err := e.Info()
		if err != nil {
			continue // gone since the read
		}
		files = append(files, file{e.Name(), info.ModTime()})
	}
	sort.Slice(files, func(i, j int) bool {
		if !files[i].mod.Equal(files[j].mod) {
			return files[i].mod.After(files[j].mod)
		}
		return files[i].name > files[j].name
	})
	var errs []error
	for i := keep; i < len(files); i++ {
		if err := os.Remove(filepath.Join(dir, files[i].name)); err != nil && !errors.Is(err, fs.ErrNotExist) {
			errs = append(errs, fmt.Errorf("session: prune: %w", err))
		}
	}
	return errors.Join(errs...)
}

// hear appends the event's line to its session's file. The first failure is
// returned to the core, which logs it; later ones return nothing.
func (s *Session) hear(instance, event string, payload []byte) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	max, ok := s.max[instance]
	if !ok {
		max = MaxBytes
	}
	err := s.pending
	s.pending = nil
	if err == nil {
		err = s.write(event, payload, max)
	}
	if err == nil || s.reported {
		return nil
	}
	s.reported = true
	return err
}

// write appends one line, under the caller's lock: the full line where it
// fits within max, else the short one.
func (s *Session) write(event string, payload []byte, max int64) error {
	at := s.o.Now()
	name, line := Line(at, event, payload, true)
	path := filepath.Join(s.o.Dir, name)
	var size int64
	if fi, err := os.Stat(path); err == nil {
		size = fi.Size()
	}
	if size+int64(len(line)) > max {
		_, line = Line(at, event, payload, false)
	}
	if err := os.MkdirAll(s.o.Dir, 0o700); err != nil {
		return fmt.Errorf("session: %w", err)
	}
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o600)
	if err != nil {
		return fmt.Errorf("session: %w", err)
	}
	_, werr := f.Write(line)
	if cerr := f.Close(); werr == nil {
		werr = cerr
	}
	if werr != nil {
		return fmt.Errorf("session: %s: %w", path, werr)
	}
	return nil
}

// safeID is a session id that is a safe file name.
var safeID = regexp.MustCompile(`^[A-Za-z0-9._-]{1,128}$`)

// full and short are a line's two forms, their fields in order.
type full struct {
	Time    string          `json:"time"`
	Event   string          `json:"event"`
	Session string          `json:"session"`
	Payload json.RawMessage `json:"payload"`
}

type short struct {
	Time    string `json:"time"`
	Event   string `json:"event"`
	Session string `json:"session"`
	Dropped int    `json:"dropped"`
}

// Line forms an event's line and the file it goes to: the event, its payload
// as the host gave it, the time it was heard and whether the payload still
// fits in its file go in; the file name (<session>.jsonl) and the line, its
// newline included, come out. It reads no clock, file or environment.
//
// The full line holds the payload compacted, or as a JSON string where it is
// no valid JSON; the short line holds dropped, the payload's size in bytes,
// in its place.
func Line(at time.Time, event string, payload []byte, fits bool) (file string, line []byte) {
	var id struct {
		Session any `json:"session_id"`
	}
	_ = json.Unmarshal(payload, &id)
	session, _ := id.Session.(string)
	file = Unknown + ".jsonl"
	if safeID.MatchString(session) && session != "." && session != ".." {
		file = session + ".jsonl"
	}
	stamp := at.UTC().Format(time.RFC3339Nano)
	var v any = short{stamp, event, session, len(payload)}
	if fits {
		var compact bytes.Buffer
		if err := json.Compact(&compact, payload); err != nil {
			quoted, _ := json.Marshal(string(payload))
			compact.Reset()
			compact.Write(quoted)
		}
		v = full{stamp, event, session, compact.Bytes()}
	}
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(v) // the fields are strings, a number and valid JSON
	return file, b.Bytes()
}
