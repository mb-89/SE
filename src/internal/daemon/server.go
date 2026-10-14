package daemon

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"sync/atomic"
	"time"

	"github.com/mb-89/SE/src/internal/index"
	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/session"
)

// bodyCap bounds one post.
const bodyCap = 16 << 20

// Server answers the bridgehead's posts for one workspace.
type Server struct {
	ix       *index.Index
	posts    string
	token    string
	instance string
	shutdown func()
	clock    clock.Clock
	seq      atomic.Uint64
	last     atomic.Int64
}

// NewServer makes the handler side of a daemon on the started index ix: each
// post is committed to the instance of the session posts module the wiring
// names. shutdown runs when /shutdown is posted, and clk says how long it has idled.
func NewServer(ix *index.Index, token, instance string, shutdown func(), clk clock.Clock) *Server {
	s := &Server{ix: ix, token: token, instance: instance, shutdown: shutdown, clock: clk}
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

// Handler routes /health, /event, /value/<name> and /shutdown, each behind the token.
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", s.health)
	mux.HandleFunc("POST /event", s.event)
	mux.HandleFunc("GET /value/{name...}", s.value)
	mux.HandleFunc("POST /shutdown", s.stop)
	return s.authorized(mux)
}

func (s *Server) authorized(next http.Handler) http.Handler {
	want := []byte("Bearer " + s.token)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), want) != 1 {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (s *Server) health(w http.ResponseWriter, _ *http.Request) {
	answer(w, map[string]any{"protocolVersion": ProtocolVersion, "instanceId": s.instance, "pid": os.Getpid()})
}

func (s *Server) stop(w http.ResponseWriter, _ *http.Request) {
	answer(w, map[string]any{})
	if s.shutdown != nil {
		go s.shutdown()
	}
}

// event is where every forwarded session event arrives: a breakpoint here holds the session.
func (s *Server) event(w http.ResponseWriter, r *http.Request) {
	s.touch()
	var ev session.Event
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, bodyCap)).Decode(&ev); err != nil {
		http.Error(w, "bad event: "+err.Error(), http.StatusBadRequest)
		return
	}
	if !session.Named(ev.Session) || ev.Event == "" {
		http.Error(w, "bad event: session and event are required", http.StatusBadRequest)
		return
	}
	if err := s.Post(ev); err != nil {
		http.Error(w, "append: "+err.Error(), http.StatusInternalServerError)
		return
	}
	answer(w, map[string]any{})
}

// Post commits the event as the session posts module's next one; the
// modules that read it, the session log among them, run before it returns.
func (s *Server) Post(ev session.Event) error {
	if s.posts == "" {
		return errors.New("the wiring names no instance of the session posts module")
	}
	ev.Seq = s.seq.Add(1)
	return s.ix.Commit(s.posts, session.Events.Set(ev))
}

// value answers a name's value on the index, and whether anything provided it.
func (s *Server) value(w http.ResponseWriter, r *http.Request) {
	v, err := s.ix.Read(r.PathValue("name"))
	if err != nil {
		http.Error(w, err.Error(), http.StatusNotFound)
		return
	}
	answer(w, map[string]any{"value": v.V, "provided": v.Provided})
}

func answer(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(v)
}
