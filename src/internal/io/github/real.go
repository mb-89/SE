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
	// requests counts the requests made; rate is the quota GitHub's last
	// answer gave (Meter).
	requests int
	rate     Rate
}

// Requests answers how many requests went to GitHub, a List's pages each one.
func (r *rest) Requests() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.requests
}

// Rate answers the quota as GitHub's last answer gave it.
func (r *rest) Rate() Rate {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.rate
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
	resp, err := r.client.Do(req)
	r.mu.Lock()
	r.requests++
	r.mu.Unlock()
	if err != nil {
		return nil, fmt.Errorf("%s %s: %w", method, path, err)
	}
	defer resp.Body.Close()
	h := map[string]string{}
	for k := range resp.Header {
		h[strings.ToLower(k)] = resp.Header.Get(k)
	}
	rate := rateOf(h)
	if rate.Known {
		r.mu.Lock()
		r.rate = rate
		r.mu.Unlock()
	}
	out, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("%s %s: %w", method, path, err)
	}
	switch {
	case resp.StatusCode == http.StatusNotModified && had.etag != "":
		return had.body, nil
	case resp.StatusCode == http.StatusUnauthorized:
		return nil, &Error{Status: resp.StatusCode, Message: notSignedIn, Rate: rate}
	case resp.StatusCode/100 != 2:
		return nil, &Error{Status: resp.StatusCode, Message: fmt.Sprintf("%s %s: %s", method, path, refusal(out)), Rate: rate}
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
