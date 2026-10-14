package daemon

import (
	"crypto/subtle"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
)

// PayloadCap is the longest event input a row carries whole; a longer one lands cut.
const PayloadCap = 4000

// bodyCap bounds one post.
const bodyCap = 16 << 20

var sessionName = regexp.MustCompile(`^[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}$`)

// Event is one post of the bridgehead: a session event as the engine raised it.
type Event struct {
	Session string          `json:"session"`
	Event   string          `json:"event"`
	At      string          `json:"at"`
	E       json.RawMessage `json:"e"`
}

// Server answers the bridgehead's posts for one workspace.
type Server struct {
	paths    Paths
	token    string
	instance string
	shutdown func()
	clock    clock.Clock
	mu       sync.Mutex
	last     atomic.Int64
}

// NewServer makes the handler side of a daemon; shutdown runs when /shutdown
// is posted, and clk says how long it has idled.
func NewServer(paths Paths, token, instance string, shutdown func(), clk clock.Clock) *Server {
	s := &Server{paths: paths, token: token, instance: instance, shutdown: shutdown, clock: clk}
	s.touch()
	return s
}

func (s *Server) touch() { s.last.Store(s.clock.Now().UnixNano()) }

// Idle is how long the server has gone without a post.
func (s *Server) Idle() time.Duration { return s.clock.Now().Sub(time.Unix(0, s.last.Load())) }

// Handler routes /health, /event and /shutdown, each behind the token.
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", s.health)
	mux.HandleFunc("POST /event", s.event)
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
	var ev Event
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, bodyCap)).Decode(&ev); err != nil {
		http.Error(w, "bad event: "+err.Error(), http.StatusBadRequest)
		return
	}
	if !sessionName.MatchString(ev.Session) || ev.Event == "" {
		http.Error(w, "bad event: session and event are required", http.StatusBadRequest)
		return
	}
	if err := s.Append(ev); err != nil {
		http.Error(w, "append: "+err.Error(), http.StatusInternalServerError)
		return
	}
	answer(w, map[string]any{})
}

// Append adds the event as one line to its session's log.
func (s *Server) Append(ev Event) error {
	line, err := json.Marshal(map[string]any{"at": ev.At, "event": ev.Event, "e": payloadOf(ev.E)})
	if err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	f, err := os.OpenFile(filepath.Join(s.paths.Logs(), ev.Session+".jsonl"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
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

func answer(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(v)
}
