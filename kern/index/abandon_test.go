package index_test

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/mb-89/kern/index"
)

// held is a declared component whose one command asks the desk once and
// answers what the desk said; its process is the case's heldRemote.
const heldDeclaration = `name = "held"
contract = 1
help = "Holds a call while the desk answers."

[commands."held on"]
usage = "held on NAME"
summary = "Ask the desk, then answer."
group = "Fixtures"
help = "Asks the desk for NAME, and answers the desk's answer."
class = "batch"

[requests.ask]
type = "string"
answer = "string"
help = "The question to the desk."
`

// heldRemote answers each first step with a request for the desk and a
// continuation, each later one with the answer, and records the stop words.
type heldRemote struct {
	mu      sync.Mutex
	stopped map[string]string
	steps   []index.Step
}

func (r *heldRemote) Command(_ context.Context, _ string, s index.Step, _ func(string)) (index.Answer, error) {
	r.mu.Lock()
	r.steps = append(r.steps, s)
	r.mu.Unlock()
	if s.Step == 1 {
		q, _ := json.Marshal(s.Args[0])
		return index.Answer{Requests: []index.WireAsk{{Port: "ask", Value: q}}, Then: true}, nil
	}
	var answers []string
	_ = json.Unmarshal(s.Answers, &answers)
	return index.Answer{Text: "call " + s.Call + ": " + answers[0]}, nil
}

func (r *heldRemote) Stop(_, call, reason string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.stopped[call] = reason
}

func (r *heldRemote) Serve(context.Context, string, json.RawMessage) (json.RawMessage, error) {
	return nil, errors.New("held serves no verb")
}

func (r *heldRemote) stops() map[string]string {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := map[string]string{}
	for k, v := range r.stopped {
		out[k] = v
	}
	return out
}

// desk answers each question once the case lets it go, or refuses "refuse".
func heldIndex(t *testing.T) (*index.Index, *heldRemote, chan struct{}) {
	t.Helper()
	release := make(chan struct{})
	desk := index.Declare("desk", "Answers questions.", index.IO(),
		index.Verb("answer", "Answers once the case lets it go.", func(_ context.Context, q string) (string, error) {
			if q == "refuse" {
				return "", errors.New("the desk refuses")
			}
			<-release
			return "yes " + q, nil
		}))
	held, err := index.ParseDeclaration([]byte(heldDeclaration))
	if err != nil {
		t.Fatal(err)
	}
	remote := &heldRemote{stopped: map[string]string{}}
	held.SetRemote(remote)
	w, err := index.ParseWiring([]byte(`
[instances.desk]
component = "desk"

[instances.held]
component = "held"

[wires]
"held.ask" = "desk.answer"
`))
	if err != nil {
		t.Fatal(err)
	}
	ix, err := index.Start(w, desk, held)
	if err != nil {
		t.Fatal(err)
	}
	return ix, remote, release
}

// A call given up while its request waits fails at once with the cause, and
// the declared component is told on the call's own stop word, so its
// continuation ends; a call of the same command beside it is not touched and
// runs its continuation to the end. A request that fails tells it too.
func TestACallGivenUpTellsItsComponentAndLeavesTheCallBesideIt(t *testing.T) {
	t.Parallel()
	ix, remote, release := heldIndex(t)
	type ended struct {
		r   index.Result
		err error
	}
	sibling := make(chan ended, 1)
	ctx, cancel := context.WithCancelCause(context.Background())
	given := make(chan ended, 1)
	go func() {
		r, err := ix.CallContext(ctx, "held on", nil, "a")
		given <- ended{r, err}
	}()
	waitSteps(t, remote, 1)
	go func() {
		r, err := ix.CallContext(context.Background(), "held on", nil, "b")
		sibling <- ended{r, err}
	}()
	waitSteps(t, remote, 2)
	cancel(errors.New("its caller gave it up"))
	var g ended
	select {
	case g = <-given:
	case <-time.After(10 * time.Second):
		t.Fatal("the given-up call still waits for its request")
	}
	if g.err == nil || !strings.Contains(g.err.Error(), "the call is given up: its caller gave it up") {
		t.Fatalf("the given-up call ends with %v, and wants the cause named", g.err)
	}
	stops := remote.stops()
	if len(stops) != 1 || !strings.Contains(stops["1"], "its caller gave it up") {
		t.Fatalf("the component is told %v, and wants call 1 alone given up", stops)
	}
	close(release)
	select {
	case s := <-sibling:
		if s.err != nil || s.r.Text != "call 2: yes b" {
			t.Fatalf("the call beside it answers %+v, %v, and wants its continuation's text", s.r, s.err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("the call beside the given-up one never answers")
	}
	if len(remote.stops()) != 1 {
		t.Fatalf("the component is told %v, and wants no stop word for the call that ended", remote.stops())
	}

	if _, err := ix.Call("held on", "refuse"); err == nil || !strings.Contains(err.Error(), "the desk refuses") {
		t.Fatalf("a refused request ends the call with %v, and wants the refusal", err)
	}
	if stop := remote.stops()["3"]; !strings.Contains(stop, "the desk refuses") {
		t.Fatalf("a call its request failed tells the component %q, and wants the failure", stop)
	}
}

func waitSteps(t *testing.T, r *heldRemote, n int) {
	t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		r.mu.Lock()
		got := len(r.steps)
		r.mu.Unlock()
		if got >= n {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("the component ran fewer than %d steps", n)
}
