package github_test

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/mb-89/kern/bus"
	"github.com/mb-89/kern/components/github"
	"github.com/mb-89/kern/host"
	"github.com/mb-89/kern/index"
)

// clock is the read times' clock; the case moves it.
type clock struct {
	mu  sync.Mutex
	now time.Time
}

func (c *clock) Now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.now
}

func (c *clock) move(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.now = c.now.Add(d)
}

var nine = time.Date(2026, 11, 13, 9, 0, 0, 0, time.UTC)

// reader is another component, which reads GitHub through the component's
// verbs alone: its command `read <verb> <owner> <repo> <n>` shows the title or
// the count of check runs it is answered.
var reader = func() *index.Component {
	issue := index.Request[github.Ref, github.Snapshot]("issue", "Reads an issue.")
	pull := index.Request[github.Ref, github.Snapshot]("pull", "Reads a pull request.")
	checks := index.Request[github.Ref, github.Snapshot]("checks", "Reads a pull request's check runs.")
	ports := map[string]*index.RequestPort[github.Ref, github.Snapshot]{"issue": issue, "pull": pull, "checks": checks}
	return index.Declare("reader", "Reads GitHub through the github component.", issue, pull, checks,
		index.Command(index.CommandDecl{
			Name: "read", Usage: "read VERB OWNER REPO N", Summary: "Read one thing.", Help: "Shows what it reads.",
			Group: "Fixtures", Class: index.Batch,
		}, func(_ struct{}, args []string) (index.Result, error) {
			var n int
			fmt.Sscanf(args[3], "%d", &n)
			p := ports[args[0]]
			return index.Result{Requests: []index.Ask{p.Ask(github.Ref{Owner: args[1], Repo: args[2], Number: n})}, Then: func(a []any) (index.Result, error) {
				s := p.Answer(a[0])
				data, _ := s.Data.(map[string]any)
				if args[0] == "checks" {
					return index.Result{Text: fmt.Sprintf("%v check runs, read %s via %s", data["total_count"], s.Read.Format(time.RFC3339), s.Via)}, nil
				}
				return index.Result{Text: fmt.Sprintf("%v, read %s via %s", data["title"], s.Read.Format(time.RFC3339), s.Via)}, nil
			}}, nil
		}),
	)
}()

// wiring is a checkout's wiring with the component and the reader.
func wiring(t *testing.T, config string) index.Wiring {
	t.Helper()
	w, err := index.ParseWiring([]byte(fmt.Sprintf(`
[instances.github]
component = "github"
config = { %s }

[instances.reader]
component = "reader"

[wires]
"github.issues" = "github/issues/<key>"
"github.pulls" = "github/pulls/<key>"
"github.checks" = "github/checks/<key>"
"github.comments" = "github/comments/<key>"
"github.outbox" = "github/outbox/<key>"
"reader.issue" = "github.issue"
"reader.pull" = "github.pull"
"reader.checks" = "github.check-runs"
`, config)))
	if err != nil {
		t.Fatal(err)
	}
	return w
}

// fakeGitHub is GitHub's REST API as the token backend reads it: an issue,
// a pull request and its check runs, each with an ETag, and the refusals a
// case queues before them.
type fakeGitHub struct {
	mu       sync.Mutex
	bodies   map[string]string
	refusals []func(http.ResponseWriter)
	asked    []string // each request: its path, and its If-None-Match where it sent one
	answered []int
}

func newFake(t *testing.T) (*fakeGitHub, *httptest.Server) {
	f := &fakeGitHub{bodies: map[string]string{
		"/repos/alice/demo/issues/7":                  `{"number": 7, "title": "One issue", "state": "open"}`,
		"/repos/alice/demo/pulls/8":                   `{"number": 8, "title": "One pull", "head": {"sha": "abc123"}}`,
		"/repos/alice/demo/commits/abc123/check-runs": `{"total_count": 2, "check_runs": [{"name": "check"}, {"name": "kern-windows"}]}`,
	}}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.mu.Lock()
		defer f.mu.Unlock()
		f.asked = append(f.asked, strings.TrimSpace(r.URL.Path+" "+r.Header.Get("If-None-Match")))
		if r.Header.Get("Authorization") != "Bearer test-token" {
			w.WriteHeader(http.StatusUnauthorized)
			f.answered = append(f.answered, http.StatusUnauthorized)
			return
		}
		if len(f.refusals) > 0 {
			f.refusals[0](w)
			f.refusals = f.refusals[1:]
			f.answered = append(f.answered, -1)
			return
		}
		body, ok := f.bodies[strings.ToLower(r.URL.Path)] // GitHub reads names regardless of case
		if !ok {
			w.WriteHeader(http.StatusNotFound)
			f.answered = append(f.answered, http.StatusNotFound)
			return
		}
		etag := fmt.Sprintf(`"%x"`, len(body))
		if r.Header.Get("If-None-Match") == etag {
			w.WriteHeader(http.StatusNotModified)
			f.answered = append(f.answered, http.StatusNotModified)
			return
		}
		w.Header().Set("ETag", etag)
		fmt.Fprint(w, body)
		f.answered = append(f.answered, http.StatusOK)
	}))
	t.Cleanup(srv.Close)
	return f, srv
}

func (f *fakeGitHub) log() ([]string, []int) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string{}, f.asked...), append([]int{}, f.answered...)
}

// started starts an index with a component made of o and the reader.
func started(t *testing.T, o github.Options, w index.Wiring) (*github.GitHub, *index.Index) {
	t.Helper()
	g := github.New(o)
	ix, err := index.Start(w, g.Component, reader)
	if err != nil {
		t.Fatal(err)
	}
	return g, ix
}

func snapshot(t *testing.T, ix *index.Index, name string) github.Snapshot {
	t.Helper()
	v, err := ix.Read(name)
	if err != nil {
		t.Fatal(err)
	}
	if !v.Provided {
		t.Fatalf("%s reads its built-in value, and wants a snapshot", name)
	}
	return v.V.(github.Snapshot)
}

func token(string) func() (string, error) {
	return func() (string, error) { return "test-token", nil }
}

func noToken() (string, error) { return "", nil }

func notCloud() bool { return false }

// The token backend reads through REST: another component's command reads
// an issue through the verb, the snapshot name holds it with its read time,
// and a second read sends the ETag and is answered 304 from what it holds.
func TestTheTokenBackendReadsWithETags(t *testing.T) {
	t.Parallel()
	f, srv := newFake(t)
	clk := &clock{now: nine}
	_, ix := started(t, github.Options{Now: clk.Now, Token: token(""), Cloud: notCloud, Every: func(time.Duration, func()) {}},
		wiring(t, fmt.Sprintf(`backend = "auto", api = %q`, srv.URL)))
	if v, _ := ix.Read("github/backend"); v.V != github.Token {
		t.Fatalf("github/backend reads %v, and wants token where a token is found", v.V)
	}
	r, err := ix.Call("read", "issue", "Alice", "demo", "7")
	if err != nil || r.Text != "One issue, read 2026-11-13T09:00:00Z via token" {
		t.Fatalf("read answers %q, %v", r.Text, err)
	}
	s := snapshot(t, ix, "github/issues/alice.demo.7")
	if s.Read != nine || s.Via != github.Token || s.Repo != "alice/demo" || s.Number != 7 {
		t.Fatalf("the snapshot is %+v", s)
	}
	clk.move(time.Minute)
	if r, err = ix.Call("read", "issue", "alice", "demo", "7"); err != nil || !strings.Contains(r.Text, "09:01:00Z") {
		t.Fatalf("the second read answers %q, %v", r.Text, err)
	}
	asked, answered := f.log()
	want := []string{"/repos/alice/demo/issues/7", `/repos/alice/demo/issues/7 "34"`}
	if fmt.Sprint(asked) != fmt.Sprint(want) || fmt.Sprint(answered) != "[200 304]" {
		t.Fatalf("GitHub was asked %q and answered %v, and wants %q answered [200 304]", asked, answered, want)
	}
}

// A pull request's check runs are read at its head, and land beside the pull request.
func TestTheTokenBackendReadsAPullsCheckRuns(t *testing.T) {
	t.Parallel()
	_, srv := newFake(t)
	_, ix := started(t, github.Options{Now: (&clock{now: nine}).Now, Token: token(""), Cloud: notCloud, Every: func(time.Duration, func()) {}},
		wiring(t, fmt.Sprintf(`backend = "token", api = %q`, srv.URL)))
	r, err := ix.Call("read", "checks", "alice", "demo", "8")
	if err != nil || r.Text != "2 check runs, read 2026-11-13T09:00:00Z via token" {
		t.Fatalf("read checks answers %q, %v", r.Text, err)
	}
	snapshot(t, ix, "github/checks/alice.demo.8")
	if r, err = ix.Call("read", "pull", "alice", "demo", "8"); err != nil || !strings.HasPrefix(r.Text, "One pull,") {
		t.Fatalf("read pull answers %q, %v", r.Text, err)
	}
	snapshot(t, ix, "github/pulls/alice.demo.8")
	if err := ix.Hear(github.PostToolUse, toolUse("mcp__github__issue_read", map[string]any{"method": "get_comments", "owner": "alice", "repo": "demo", "issue_number": 7}, `[{"id": 1, "body": "Started"}]`)); err != nil {
		t.Fatal(err)
	}
	if s := snapshot(t, ix, "github/comments/alice.demo.7"); len(s.Data.([]any)) != 1 {
		t.Fatalf("the comments snapshot holds %v", s.Data)
	}
}

// The refresh reads each snapshot the token holds again, with its ETag, and
// a changed answer moves the snapshot.
func TestTheRefreshReadsEverySnapshotAgain(t *testing.T) {
	t.Parallel()
	f, srv := newFake(t)
	clk := &clock{now: nine}
	var every time.Duration
	var refresh func()
	_, ix := started(t, github.Options{Now: clk.Now, Token: token(""), Cloud: notCloud, Every: func(d time.Duration, fn func()) { every, refresh = d, fn }},
		wiring(t, fmt.Sprintf(`api = %q`, srv.URL)))
	if every != 2*time.Minute || refresh == nil {
		t.Fatalf("the refresh runs every %v, and wants every 2m", every)
	}
	if _, err := ix.Call("read", "issue", "alice", "demo", "7"); err != nil {
		t.Fatal(err)
	}
	f.mu.Lock()
	f.bodies["/repos/alice/demo/issues/7"] = `{"number": 7, "title": "One issue, renamed", "state": "closed"}`
	f.mu.Unlock()
	clk.move(2 * time.Minute)
	refresh()
	s := snapshot(t, ix, "github/issues/alice.demo.7")
	if s.Read != nine.Add(2*time.Minute) || s.Data.(map[string]any)["title"] != "One issue, renamed" {
		t.Fatalf("after the refresh the snapshot is %+v", s)
	}
	if _, answered := f.log(); fmt.Sprint(answered) != "[200 200]" {
		t.Fatalf("GitHub answered %v, and wants the changed issue read again: [200 200]", answered)
	}
}

// The token backend paces on 403 and 429: it waits what Retry-After or the
// quota's reset asks, and every read waits with it; a 403 that is no rate
// limit fails at once, and a wait over pace-max fails the read.
func TestTheTokenBackendPacesOnRateLimits(t *testing.T) {
	t.Parallel()
	for _, c := range []struct {
		name    string
		refusal func(w http.ResponseWriter)
		slept   string
		err     string
	}{
		{"429 with Retry-After", func(w http.ResponseWriter) {
			w.Header().Set("Retry-After", "3")
			w.WriteHeader(http.StatusTooManyRequests)
		}, "[3s]", ""},
		{"403 with the quota spent", func(w http.ResponseWriter) {
			w.Header().Set("X-RateLimit-Remaining", "0")
			w.Header().Set("X-RateLimit-Reset", fmt.Sprint(nine.Add(40*time.Second).Unix()))
			w.WriteHeader(http.StatusForbidden)
		}, "[40s]", ""},
		{"403 of a secondary limit", func(w http.ResponseWriter) {
			w.Header().Set("Retry-After", "20")
			w.WriteHeader(http.StatusForbidden)
		}, "[20s]", ""},
		{"403 that is no limit", func(w http.ResponseWriter) {
			w.WriteHeader(http.StatusForbidden)
			fmt.Fprint(w, `{"message": "Resource not accessible"}`)
		}, "[]", "403 Forbidden"},
		{"a wait over pace-max", func(w http.ResponseWriter) {
			w.Header().Set("Retry-After", "600")
			w.WriteHeader(http.StatusTooManyRequests)
		}, "[]", "over pace-max 1m0s"},
	} {
		t.Run(c.name, func(t *testing.T) {
			f, srv := newFake(t)
			f.refusals = append(f.refusals, c.refusal)
			clk := &clock{now: nine}
			var slept []time.Duration
			_, ix := started(t, github.Options{Now: clk.Now, Token: token(""), Cloud: notCloud, Every: func(time.Duration, func()) {},
				Sleep: func(d time.Duration) { slept = append(slept, d); clk.move(d) }},
				wiring(t, fmt.Sprintf(`api = %q`, srv.URL)))
			r, err := ix.Call("read", "issue", "alice", "demo", "7")
			if fmt.Sprint(slept) != c.slept {
				t.Fatalf("the backend slept %v, and wants %s", slept, c.slept)
			}
			if c.err == "" && (err != nil || !strings.HasPrefix(r.Text, "One issue")) {
				t.Fatalf("read answers %q, %v, and wants the issue after the wait", r.Text, err)
			}
			if c.err != "" && (err == nil || !strings.Contains(err.Error(), c.err)) {
				t.Fatalf("read fails with %v, and wants %q", err, c.err)
			}
		})
	}
}

// In a cloud session auto takes the relay, though a token stands in the
// environment: there it is the proxy's stand-in, which code cannot use. A
// backend named token still takes it.
func TestAutoTakesTheRelayInACloudSession(t *testing.T) {
	t.Parallel()
	for backend, want := range map[string]string{"auto": github.Relay, "token": github.Token} {
		_, ix := started(t, github.Options{Token: token(""), Cloud: func() bool { return true }, Every: func(time.Duration, func()) {}},
			wiring(t, fmt.Sprintf(`backend = %q`, backend)))
		if v, _ := ix.Read("github/backend"); v.V != want {
			t.Fatalf("backend %s in a cloud session reads %v, and wants %s", backend, v.V, want)
		}
	}
}

// A start that asks for the token where none is found is refused.
func TestTheTokenBackendWithoutATokenIsRefused(t *testing.T) {
	t.Parallel()
	_, err := index.Start(wiring(t, `backend = "token"`), github.New(github.Options{Token: noToken}).Component, reader)
	if err == nil || !strings.Contains(err.Error(), "no token is found") {
		t.Fatalf("the start answers %v, and wants it refused: no token is found", err)
	}
}

// toolUse is a PostToolUse payload as a cloud session's hook hands it
// (docs/go-core.md, "What the hooks carry, probed in a cloud session").
func toolUse(tool string, input map[string]any, answer string) []byte {
	text, _ := json.Marshal(answer)
	in, _ := json.Marshal(input)
	return []byte(fmt.Sprintf(`{"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": %q, "tool_input": %s,
		"tool_use_id": "toolu_1", "duration_ms": 412, "mcp_server": {"name": "github", "source": "dynamic"},
		"tool_response": [{"type": "text", "text": %s}]}`, tool, in, text))
}

var issueRead = map[string]any{"method": "get", "owner": "alice", "repo": "demo", "issue_number": 7}

// Without a token the relay answers: a read goes out as an outbox step with
// the tool call that answers it, and fails naming it; the session's tool
// answer, handed over by PostToolUse, lands in the snapshot, drops the step,
// and the next read answers from the snapshot without asking.
func TestTheRelayAsksOnTheOutboxAndPostToolUseAnswers(t *testing.T) {
	t.Parallel()
	clk := &clock{now: nine}
	_, ix := started(t, github.Options{Now: clk.Now, Token: noToken}, wiring(t, ``))
	if v, _ := ix.Read("github/backend"); v.V != github.Relay {
		t.Fatalf("github/backend reads %v, and wants relay where no token is found", v.V)
	}
	_, err := ix.Call("read", "issue", "alice", "demo", "7")
	if err == nil || !strings.Contains(err.Error(), `run the GitHub tool issue_read with {"issue_number":7,"method":"get","owner":"alice","repo":"demo"}; outbox step issue.alice.demo.7`) {
		t.Fatalf("the read answers %v, and wants it to name the tool call it waits for", err)
	}
	v, _ := ix.Read("github/outbox/issue.alice.demo.7")
	if step := v.V.(github.Step); step.Tool != "issue_read" || step.Asked != nine {
		t.Fatalf("the outbox holds %+v", v.V)
	}
	clk.move(5 * time.Second)
	if err := ix.Hear(github.PostToolUse, toolUse("mcp__github__issue_read", issueRead, `{"number": 7, "title": "One issue"}`)); err != nil {
		t.Fatal(err)
	}
	s := snapshot(t, ix, "github/issues/alice.demo.7")
	if s.Read != nine.Add(5*time.Second) || s.Via != github.Relay {
		t.Fatalf("the snapshot is %+v, and wants it read at 09:00:05 via relay", s)
	}
	if v, _ := ix.Read("github/outbox/issue.alice.demo.7"); v.Provided {
		t.Fatalf("the answered step stands in the outbox: %+v", v.V)
	}
	clk.move(time.Minute)
	r, err := ix.Call("read", "issue", "alice", "demo", "7")
	if err != nil || r.Text != "One issue, read 2026-11-13T09:00:05Z via relay" {
		t.Fatalf("the next read answers %q, %v, and wants the snapshot", r.Text, err)
	}
	clk.move(2 * time.Minute)
	if _, err := ix.Call("read", "issue", "alice", "demo", "7"); err == nil {
		t.Fatal("a read after the snapshot aged past refresh answers, and wants it asked again")
	}
}

// With relay-wait, a read waits for the session's answer and is answered by it.
func TestARelayReadWaitsForTheToolAnswer(t *testing.T) {
	t.Parallel()
	_, ix := started(t, github.Options{Now: (&clock{now: nine}).Now, Token: noToken}, wiring(t, `relay-wait = "10s"`))
	go func() {
		for {
			if v, _ := ix.Read("github/outbox/check-runs.alice.demo.8"); v.Provided {
				_ = ix.Hear(github.PostToolUse, toolUse("mcp__0f1e2d3c__pull_request_read",
					map[string]any{"method": "get_check_runs", "owner": "alice", "repo": "demo", "pullNumber": 8},
					`{"total_count": 2, "check_runs": []}`))
				return
			}
			time.Sleep(time.Millisecond)
		}
	}()
	r, err := ix.Call("read", "checks", "alice", "demo", "8")
	if err != nil || r.Text != "2 check runs, read 2026-11-13T09:00:00Z via relay" {
		t.Fatalf("the waiting read answers %q, %v", r.Text, err)
	}
}

// Every GitHub tool answer lands, asked or not; other tools, other methods,
// other events and error answers write nothing.
func TestEveryGitHubToolAnswerLandsAndNothingElse(t *testing.T) {
	t.Parallel()
	_, ix := started(t, github.Options{Now: (&clock{now: nine}).Now, Token: noToken}, wiring(t, ``))
	before := ix.Snapshot().Revision()
	for _, p := range [][]byte{
		toolUse("Bash", map[string]any{"command": "ls"}, "{}"),
		toolUse("mcp__github__issue_read", map[string]any{"method": "get_labels", "owner": "alice", "repo": "demo", "issue_number": 7}, "[]"),
		[]byte(`not json`),
	} {
		if err := ix.Hear(github.PostToolUse, p); err != nil {
			t.Fatal(err)
		}
	}
	if err := ix.Hear("PreToolUse", toolUse("mcp__github__issue_read", issueRead, `{"number": 7}`)); err != nil {
		t.Fatal(err)
	}
	if err := ix.Hear(github.PostToolUse, []byte(`{"tool_name": "mcp__github__issue_read", "tool_input": {"method": "get", "owner": "alice", "repo": "demo", "issue_number": 7},
		"tool_response": {"content": [{"type": "text", "text": "Not Found"}], "isError": true}}`)); err == nil {
		t.Fatal("an error answer is heard without a word, and wants it named")
	}
	if rev := ix.Snapshot().Revision(); rev != before {
		t.Fatalf("the store moved from revision %d to %d", before, rev)
	}
	if err := ix.Hear(github.PostToolUse, toolUse("mcp__github__pull_request_read", map[string]any{"method": "get", "owner": "Alice", "repo": "Demo", "pullNumber": "8"}, `{"number": 8}`)); err != nil {
		t.Fatal(err)
	}
	snapshot(t, ix, "github/pulls/alice.demo.8")
}

// Switched off, the component reads no token, hears nothing, and its names
// read their built-in values.
func TestTheComponentSwitchesOff(t *testing.T) {
	t.Parallel()
	asked := false
	w, err := index.ParseWiring([]byte(`
[instances.github]
component = "github"
enabled = false
`))
	if err != nil {
		t.Fatal(err)
	}
	_, ix := started(t, github.Options{Token: func() (string, error) { asked = true; return "", nil }}, w)
	if asked {
		t.Fatal("a switched-off component looked for a token")
	}
	if err := ix.Hear(github.PostToolUse, toolUse("mcp__github__issue_read", issueRead, `{"number": 7}`)); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"github/backend", "github/issues/alice.demo.7"} {
		if v, _ := ix.Read(name); v.Provided {
			t.Fatalf("%s reads %v, and wants its built-in value", name, v.V)
		}
	}
}

// Through the real core: the hook's post of a PostToolUse lands the issue in
// its snapshot name, which a client reads with its read time.
func TestAHookPostLandsASnapshotInTheCore(t *testing.T) {
	t.Parallel()
	g := github.New(github.Options{Now: (&clock{now: nine}).Now, Token: noToken})
	w, err := index.ParseWiring([]byte(`
[instances.github]
component = "github"

[wires]
"github.issues" = "github/issues/<key>"
`))
	if err != nil {
		t.Fatal(err)
	}
	c, err := host.Serve(host.Options{Root: t.TempDir(), Wiring: w, Components: []*index.Component{g.Component}})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { c.Stop("the case ends"); <-c.Ended() })
	s, _ := c.Standing()
	if _, err := host.Post(host.Wall{}, s.Root, github.PostToolUse, toolUse("mcp__github__issue_read", issueRead, `{"number": 7, "title": "One issue"}`), 10*time.Second); err != nil {
		t.Fatal(err)
	}
	nc, err := bus.Dial(s.Bus, bus.Client, s.Users[bus.Client])
	if err != nil {
		t.Fatal(err)
	}
	defer nc.Close()
	m, err := nc.Request(bus.Get+"github", []byte(`{"name": "github/issues/alice.demo.7"}`), 10*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	var got struct {
		Value    github.Snapshot `json:"value"`
		Provided bool            `json:"provided"`
	}
	if err := json.Unmarshal(m.Data, &got); err != nil || !got.Provided || got.Value.Read != nine || got.Value.Via != github.Relay {
		t.Fatalf("get answers %s, and wants the snapshot read at 09:00 via relay", m.Data)
	}
}
