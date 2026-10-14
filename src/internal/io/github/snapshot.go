package github

import (
	"errors"
	"sync"
	"time"
)

// Snapshot is GitHub's answers to a set of reads, as they stood At: what the
// daemon keeps warm, so a command answers from it without asking GitHub.
type Snapshot struct {
	// Repo is the repository the reads were about, OWNER/NAME.
	Repo string `json:"repo"`
	// At is when the reads began: no answer is older.
	At time.Time `json:"at"`
	// Answers is each read's answer, by "GET path" or "LIST path".
	Answers map[string]string `json:"answers"`
}

// Taken says whether the snapshot holds any answer.
func (s Snapshot) Taken() bool { return len(s.Answers) > 0 }

// ErrReadOnly is a Recorder refusing a write: a snapshot is read, never written.
var ErrReadOnly = errors.New("github: a snapshot is only read; the write was not sent")

// Recorder is GitHub read through and recorded: each answer it reads is kept
// for the Snapshot, and every write is refused with ErrReadOnly.
type Recorder struct {
	gh      GitHub
	mu      sync.Mutex
	answers map[string]string
}

// Record answers a Recorder that reads through gh.
func Record(gh GitHub) *Recorder { return &Recorder{gh: gh, answers: map[string]string{}} }

func (r *Recorder) keep(key string, out []byte, err error) ([]byte, error) {
	if err == nil {
		r.mu.Lock()
		r.answers[key] = string(out)
		r.mu.Unlock()
	}
	return out, err
}

func (r *Recorder) Get(path string) ([]byte, error) {
	out, err := r.gh.Get(path)
	return r.keep("GET "+path, out, err)
}

func (r *Recorder) List(path string) ([]byte, error) {
	out, err := r.gh.List(path)
	return r.keep("LIST "+path, out, err)
}

func (r *Recorder) Send(string, string, ...Field) ([]byte, error) { return nil, ErrReadOnly }

func (r *Recorder) GraphQL(string, ...Field) ([]byte, error) { return nil, ErrReadOnly }

// Snapshot is what the recorder read, about repo, as of at.
func (r *Recorder) Snapshot(repo string, at time.Time) Snapshot {
	r.mu.Lock()
	defer r.mu.Unlock()
	answers := make(map[string]string, len(r.answers))
	for k, v := range r.answers {
		answers[k] = v
	}
	return Snapshot{Repo: repo, At: at, Answers: answers}
}

// Replay answers each read snap holds from it, and every other read and
// every write from live.
func Replay(snap Snapshot, live GitHub) GitHub { return replay{snap: snap, live: live} }

type replay struct {
	snap Snapshot
	live GitHub
}

func (r replay) Get(path string) ([]byte, error) {
	if out, ok := r.snap.Answers["GET "+path]; ok {
		return []byte(out), nil
	}
	return r.live.Get(path)
}

func (r replay) List(path string) ([]byte, error) {
	if out, ok := r.snap.Answers["LIST "+path]; ok {
		return []byte(out), nil
	}
	return r.live.List(path)
}

func (r replay) Send(method, path string, fields ...Field) ([]byte, error) {
	return r.live.Send(method, path, fields...)
}

func (r replay) GraphQL(query string, vars ...Field) ([]byte, error) {
	return r.live.GraphQL(query, vars...)
}
