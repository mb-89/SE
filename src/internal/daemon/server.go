package daemon

import (
	"errors"
	"fmt"
	"os"
	"sync/atomic"
	"time"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/modules/io/clock"
	sehttp "github.com/mb-89/SE/src/modules/io/http"
	"github.com/mb-89/SE/src/modules/io/session"
)

// Event is one post of the bridgehead: a session event as the engine raised it.
type Event = sehttp.Event

// Server answers the bridgehead's posts and the se command line's for one
// workspace: the Daemon the network serves behind the token.
type Server struct {
	ix       *index.Index
	posts    string
	instance string
	shutdown func()
	clock    clock.Clock
	seq      atomic.Uint64
	last     atomic.Int64
}

var _ sehttp.Daemon = (*Server)(nil)

// NewServer makes the handler side of a daemon on the started index ix: each
// post is committed to the instance of the session posts module the wiring
// names. shutdown runs when /shutdown is posted, and clk says how long it has idled.
func NewServer(ix *index.Index, instance string, shutdown func(), clk clock.Clock) *Server {
	s := &Server{ix: ix, instance: instance, shutdown: shutdown, clock: clk}
	for _, in := range ix.Catalog().Instances {
		if in.Module == session.Posts.Name() {
			s.posts = in.Name
		}
	}
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
	if !session.Named(ev.Session) || ev.Event == "" {
		return fmt.Errorf("%w: session and event are required", sehttp.ErrBad)
	}
	if err := s.Post(session.Event{Session: ev.Session, Event: ev.Event, At: ev.At, E: ev.E}); err != nil {
		return fmt.Errorf("append: %w", err)
	}
	return nil
}

// Post commits the event as the session posts module's next one, at its
// session; the
// modules that read it, the session log among them, run before it returns.
func (s *Server) Post(ev session.Event) error {
	if s.posts == "" {
		return errors.New("the wiring names no instance of the session posts module")
	}
	ev.Seq = s.seq.Add(1)
	return s.ix.Commit(s.posts, session.Events.At(ev.Session, ev))
}

// Value answers a name's value on the index, and whether anything provided it.
func (s *Server) Value(name string) (sehttp.Value, error) {
	v, err := s.ix.Read(name)
	if err != nil {
		return sehttp.Value{}, fmt.Errorf("%w: %w", sehttp.ErrUnknown, err)
	}
	return sehttp.Value{Value: v.V, Provided: v.Provided}, nil
}

// Command runs a command a module declared on the index, as the se command
// line posts it, and answers its reply: the index delivers the requests the
// command answers to the I/O modules' verbs and commits what it writes.
func (s *Server) Command(c sehttp.CommandCall) (sehttp.Reply, error) {
	s.touch()
	if _, ok := s.ix.Catalog().Command(c.Name); !ok {
		return sehttp.Reply{}, fmt.Errorf("%w: no command %q", sehttp.ErrUnknown, c.Name)
	}
	r, err := s.ix.Call(c.Name, c.Words...)
	if err != nil {
		return sehttp.Reply{}, err
	}
	return sehttp.Reply{Text: r.Text}, nil
}
