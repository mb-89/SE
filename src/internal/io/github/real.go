package github

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
)

// API is the root of GitHub's REST API that Real calls.
const API = "https://api.github.com"

// Real is GitHub's REST API, called in the process over one kept-alive HTTP
// client, through the environment's proxy. It authenticates as gh does: with
// GH_TOKEN or GITHUB_TOKEN where one is set, else gh's own token (gh auth
// token, read once), else with nothing, where a Claude Code cloud box's proxy
// adds the credentials, as it does for gh. No request starts a process.
func Real() GitHub { return shared }

var shared = newRest(API, sync.OnceValue(ghToken))

// RealAt is Real against the API root base, authenticated with token where
// it is not empty: GitHub Enterprise's root, or a test's server.
func RealAt(base, token string) GitHub {
	return newRest(strings.TrimSuffix(base, "/"), func() string { return token })
}

// InFlight is how many requests Real has open at once at most, well below
// the hundred GitHub allows before it limits a client.
const InFlight = 32

func newRest(base string, token func() string) *rest {
	return &rest{base: base, token: token, client: client(), seen: map[string]cached{}, slots: make(chan struct{}, InFlight)}
}

func client() *http.Client {
	return &http.Client{
		Transport: &http.Transport{
			Proxy:               http.ProxyFromEnvironment,
			ForceAttemptHTTP2:   true,
			MaxIdleConns:        64,
			MaxIdleConnsPerHost: 64,
			IdleConnTimeout:     90 * time.Second,
		},
		Timeout: 60 * time.Second,
	}
}

// notSignedIn is what a command that needs GitHub says where GitHub refuses
// its credentials: the install never asks for a login, so this is where a
// person learns of it.
const notSignedIn = "GitHub refused se's credentials: gh has no login; run gh auth login, then this command again"

// ghToken is the token gh would send: its environment's first, else what gh
// auth token says; "" where there is none.
func ghToken() string {
	for _, k := range []string{"GH_TOKEN", "GITHUB_TOKEN"} {
		if v := os.Getenv(k); v != "" {
			return v
		}
	}
	out, err := exec.Command("gh", "auth", "token").Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

// rest is the REST API at base. It keeps each GET's answer with its ETag and
// asks again with If-None-Match, so an answer that has not changed comes back
// as 304, which GitHub does not count against the rate limit.
type rest struct {
	base   string
	token  func() string
	client *http.Client
	mu     sync.Mutex
	seen   map[string]cached
	// slots holds a token per request open, InFlight at most.
	slots chan struct{}
	// clock and trace, where trace is set, time each request and tell it
	// to trace once it is answered.
	clock clock.Clock
	trace func(Request)
}

// Request is one request se sent GitHub, as a trace tells it.
type Request struct {
	// Method is the HTTP method, such as GET.
	Method string
	// Path is the path asked, below the API's root, with its query.
	Path string
	// Status is the HTTP status GitHub answered, such as 200 or 304; zero
	// where no answer came.
	Status int
	// Start is when the request was sent, and Took how long its answer took.
	Start time.Time
	Took  time.Duration
}

// Traced is g telling seen each request it sends GitHub once it is answered,
// timed on clk; seen may be told from several goroutines at once. Real is
// traced by the HTTP request, each page of a list one; any other GitHub, such
// as a Fake, by the call, a list's method LIST.
func Traced(g GitHub, clk clock.Clock, seen func(Request)) GitHub {
	if r, ok := g.(*rest); ok {
		t := newRest(r.base, r.token)
		t.clock, t.trace = clk, seen
		return t
	}
	return traced{g: g, clock: clk, seen: seen}
}

type traced struct {
	g     GitHub
	clock clock.Clock
	seen  func(Request)
}

func (t traced) tell(method, path string, start time.Time, err error) {
	status := Status(err)
	if err == nil {
		status = http.StatusOK
	}
	t.seen(Request{Method: method, Path: path, Status: status, Start: start, Took: t.clock.Now().Sub(start)})
}

func (t traced) Get(path string) ([]byte, error) {
	start := t.clock.Now()
	out, err := t.g.Get(path)
	t.tell("GET", path, start, err)
	return out, err
}

func (t traced) List(path string) ([]byte, error) {
	start := t.clock.Now()
	out, err := t.g.List(path)
	t.tell("LIST", path, start, err)
	return out, err
}

func (t traced) Send(method, path string, fields ...Field) ([]byte, error) {
	start := t.clock.Now()
	out, err := t.g.Send(method, path, fields...)
	t.tell(method, path, start, err)
	return out, err
}

func (t traced) GraphQL(query string, vars ...Field) ([]byte, error) {
	start := t.clock.Now()
	out, err := t.g.GraphQL(query, vars...)
	t.tell("POST", "graphql", start, err)
	return out, err
}

type cached struct {
	etag string
	body []byte
}

func (r *rest) Get(path string) ([]byte, error) { return r.do("GET", path, nil) }

// List asks for path page by page, adding page=k itself, and joins the
// pages. GitHub's next links name repositories/{id} for some lists, and the
// cloud box proxy refuses those. A page shorter than per_page (30 where path
// does not say) is the last; so is one that repeats the page before it, where
// a list takes no page.
func (r *rest) List(path string) ([]byte, error) {
	sep, size := "?", pageSize(path)
	if u, err := url.Parse(path); err == nil && u.RawQuery != "" {
		sep = "&"
	}
	all := []json.RawMessage{}
	var last []byte
	for k := 1; ; k++ {
		out, err := r.Get(fmt.Sprintf("%s%spage=%d", path, sep, k))
		if err != nil {
			return nil, err
		}
		if k > 1 && bytes.Equal(bytes.TrimSpace(out), last) {
			return json.Marshal(all)
		}
		last = bytes.TrimSpace(out)
		var page []json.RawMessage
		if err := json.Unmarshal(out, &page); err != nil {
			return nil, fmt.Errorf("GET %s: %v", path, err)
		}
		all = append(all, page...)
		if len(page) < size {
			return json.Marshal(all)
		}
	}
}

// pageSize is how many items a page of the list at path holds: its per_page,
// or GitHub's 30 where path does not say.
func pageSize(path string) int {
	if u, err := url.Parse(path); err == nil {
		if n, err := strconv.Atoi(u.Query().Get("per_page")); err == nil && n > 0 {
			return n
		}
	}
	return 30
}

func (r *rest) Send(method, path string, fields ...Field) ([]byte, error) {
	var body []byte
	if len(fields) > 0 {
		var err error
		if body, err = json.Marshal(object(fields)); err != nil {
			return nil, err
		}
	}
	return r.do(method, path, body)
}

func (r *rest) GraphQL(query string, vars ...Field) ([]byte, error) {
	body, err := json.Marshal(map[string]any{"query": query, "variables": object(vars)})
	if err != nil {
		return nil, err
	}
	out, err := r.do("POST", "graphql", body)
	if err != nil {
		return nil, err
	}
	var said struct {
		Errors []struct {
			Message string `json:"message"`
		} `json:"errors"`
	}
	if json.Unmarshal(out, &said) == nil && len(said.Errors) > 0 {
		msgs := make([]string, len(said.Errors))
		for k, e := range said.Errors {
			msgs[k] = e.Message
		}
		return nil, &Error{Message: "GraphQL: " + strings.Join(msgs, "; ")}
	}
	return out, nil
}

// object is the JSON object fields make: a name ending in [] adds to an
// array, and a typed field stands as the JSON value it spells where it is
// one, as gh's -F reads it.
func object(fields []Field) map[string]any {
	out := map[string]any{}
	for _, f := range fields {
		var v any = f.Value
		if f.Typed && json.Valid([]byte(f.Value)) {
			v = json.RawMessage(f.Value)
		}
		if name, ok := strings.CutSuffix(f.Name, "[]"); ok {
			list, _ := out[name].([]any)
			out[name] = append(list, v)
			continue
		}
		out[f.Name] = v
	}
	return out
}

func (r *rest) do(method, path string, body []byte) ([]byte, error) {
	status := 0
	u := r.base + "/" + strings.TrimPrefix(path, "/")
	var in io.Reader
	if body != nil {
		in = bytes.NewReader(body)
	}
	req, err := http.NewRequest(method, u, in)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("X-GitHub-Api-Version", "2022-11-28")
	req.Header.Set("User-Agent", "se")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if t := r.token(); t != "" {
		req.Header.Set("Authorization", "token "+t)
	}
	var had cached
	if method == "GET" {
		r.mu.Lock()
		had = r.seen[u]
		r.mu.Unlock()
		if had.etag != "" {
			req.Header.Set("If-None-Match", had.etag)
		}
	}
	r.slots <- struct{}{}
	defer func() { <-r.slots }()
	if r.trace != nil {
		start := r.clock.Now()
		defer func() {
			r.trace(Request{Method: method, Path: strings.TrimPrefix(path, "/"), Status: status, Start: start, Took: r.clock.Now().Sub(start)})
		}()
	}
	resp, err := r.client.Do(req)
	if resp != nil {
		status = resp.StatusCode
	}
	return r.answer(method, path, u, had, resp, err)
}

// answer reads resp, the answer to method path at u, where had is what a
// GET of u answered before.
func (r *rest) answer(method, path, u string, had cached, resp *http.Response, err error) ([]byte, error) {
	if err != nil {
		return nil, fmt.Errorf("%s %s: %w", method, path, err)
	}
	defer resp.Body.Close()
	out, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("%s %s: %w", method, path, err)
	}
	switch {
	case resp.StatusCode == http.StatusNotModified && had.etag != "":
		return had.body, nil
	case resp.StatusCode == http.StatusUnauthorized:
		return nil, &Error{Status: resp.StatusCode, Message: notSignedIn}
	case resp.StatusCode/100 != 2:
		return nil, &Error{Status: resp.StatusCode, Message: fmt.Sprintf("%s %s: %s", method, path, refusal(out))}
	}
	if etag := resp.Header.Get("ETag"); method == "GET" && etag != "" {
		r.mu.Lock()
		r.seen[u] = cached{etag: etag, body: out}
		r.mu.Unlock()
	}
	return out, nil
}

// refusal is what GitHub said in a refusal's body: its message and the
// messages of its errors, or the body itself where it is no such JSON.
func refusal(body []byte) string {
	var said struct {
		Message string `json:"message"`
		Errors  []any  `json:"errors"`
	}
	if err := json.Unmarshal(body, &said); err != nil || said.Message == "" {
		if s := strings.TrimSpace(string(body)); s != "" {
			return s
		}
		return "no answer"
	}
	parts := []string{said.Message}
	for _, e := range said.Errors {
		switch e := e.(type) {
		case string:
			parts = append(parts, e)
		case map[string]any:
			if m, ok := e["message"].(string); ok && m != "" {
				parts = append(parts, m)
			} else if c, ok := e["code"].(string); ok {
				parts = append(parts, c)
			}
		}
	}
	return strings.Join(parts, ": ")
}
