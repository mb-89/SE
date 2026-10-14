package daemon

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
	sehttp "github.com/mb-89/SE/src/internal/io/http"
)

// PayloadCap is the longest event input a row carries whole; a longer one lands cut.
const PayloadCap = 4000

var sessionName = regexp.MustCompile(`^[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}$`)

// Event is one post of the bridgehead: a session event as the engine raised it.
type Event = sehttp.Event

// Server answers the bridgehead's posts for one workspace: the Daemon the
// network serves behind the token.
type Server struct {
	paths    Paths
	instance string
	shutdown func()
	clock    clock.Clock
	mu       sync.Mutex
	last     atomic.Int64
}

var _ sehttp.Daemon = (*Server)(nil)

// NewServer makes the handler side of a daemon; shutdown runs when /shutdown
// is posted, and clk says how long it has idled.
func NewServer(paths Paths, instance string, shutdown func(), clk clock.Clock) *Server {
	s := &Server{paths: paths, instance: instance, shutdown: shutdown, clock: clk}
	s.touch()
	return s
}

func (s *Server) touch() { s.last.Store(s.clock.Now().UnixNano()) }

// Idle is how long the server has gone without a post.
func (s *Server) Idle() time.Duration { return s.clock.Now().Sub(time.Unix(0, s.last.Load())) }

// Health is the daemon's answer to /health.
func (s *Server) Health() sehttp.Health {
	return sehttp.Health{ProtocolVersion: ProtocolVersion, InstanceID: s.instance, PID: os.Getpid()}
}

// Shutdown ends the daemon, once /shutdown is answered.
func (s *Server) Shutdown() {
	if s.shutdown != nil {
		s.shutdown()
	}
}

// Event is where every forwarded session event arrives: a breakpoint here holds the session.
func (s *Server) Event(ev Event) error {
	s.touch()
	if !sessionName.MatchString(ev.Session) || ev.Event == "" {
		return fmt.Errorf("%w: session and event are required", sehttp.ErrBad)
	}
	if err := s.Append(ev); err != nil {
		return fmt.Errorf("append: %w", err)
	}
	return nil
}

// Append adds the event as one line to its session's log.
func (s *Server) Append(ev Event) error {
	line, err := json.Marshal(map[string]any{"at": ev.At, "event": ev.Event, "e": payloadOf(ev.E)})
	if err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	f, err := s.paths.Disk.Append(filepath.Join(s.paths.Logs(), ev.Session+".jsonl"))
	if err != nil {
		return err
	}
	if _, err := f.Write(append(line, '\n')); err != nil {
		f.Close()
		return err
	}
	return f.Close()
}

// payloadOf is the event input as a row carries it: whole while short, else its head and length.
func payloadOf(raw json.RawMessage) any {
	if len(raw) == 0 {
		return nil
	}
	if len(raw) <= PayloadCap {
		return raw
	}
	return map[string]any{"cut": true, "length": len(raw), "head": strings.ToValidUTF8(string(raw[:PayloadCap]), "")}
}
