package host_test

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/kern/bus"
	"github.com/mb-89/kern/host"
	"github.com/mb-89/kern/index"
)

// callerArg makes this test binary a caller's process: it calls "kept run"
// with its last-but-one argument and waits for the answer until it is killed.
const callerArg = "kern-test-caller"

func caller() int {
	nc, err := bus.Dial(os.Getenv(bus.EnvBus), bus.Client, os.Getenv(bus.EnvToken))
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	body, _ := json.Marshal(map[string]any{"args": []string{os.Args[len(os.Args)-2]}})
	fmt.Println("calling")
	_, err = nc.Request(bus.Call+bus.Token("kept run"), body, time.Hour)
	fmt.Fprintln(os.Stderr, err)
	return 1
}

// keptWiring is a command whose one request the keeper holds until its call
// is given up, which it reports with its cause, or until the case lets it go.
func keptWiring(t *testing.T) (index.Wiring, []*index.Component, chan string, chan error, chan struct{}) {
	t.Helper()
	held, gone, release := make(chan string, 4), make(chan error, 4), make(chan struct{})
	keep := index.Request[string, string]("keep", "Holds until its call is given up.")
	keeper := index.Declare("keeper", "Keeps a request.", index.IO(),
		index.Verb("keep", "Holds until its call is given up or the case lets it go.", func(ctx context.Context, s string) (string, error) {
			held <- s
			select {
			case <-ctx.Done():
				gone <- fmt.Errorf("%s: %w", s, context.Cause(ctx))
				return "", ctx.Err()
			case <-release:
				return "let go " + s, nil
			}
		}))
	runner := index.Declare("kept", "Runs a kept command.", keep,
		index.Command(index.CommandDecl{
			Name: "kept run", Usage: "kept run WORD", Summary: "Run kept.", Help: "Asks the keeper and answers its answer.",
			Group: "Fixtures", Class: index.Batch,
		}, func(_ struct{}, args []string) (index.Result, error) {
			return index.Result{Requests: []index.Ask{keep.Ask(args[0])},
				Then: func(a []any) (index.Result, error) { return index.Result{Text: a[0].(string)}, nil }}, nil
		}))
	w, err := index.ParseWiring([]byte(`
[instances.keeper]
component = "keeper"

[instances.kept]
component = "kept"

[wires]
"kept.keep" = "keeper.keep"
`))
	if err != nil {
		t.Fatal(err)
	}
	return w, []*index.Component{keeper, runner}, held, gone, release
}

// A caller killed outright sends no call.core.abandon: the core finds that
// no connection hears its call's reply subject any more and gives the call
// up as if it had, within the lease lapse; a live caller's call beside it
// runs on to its end.
func TestAKilledCallersCallIsGivenUp(t *testing.T) {
	t.Parallel()
	w, comps, held, gone, release := keptWiring(t)
	c := served(t, host.Options{Clock: newClock(), Wiring: w, Components: comps, CallBeat: 50 * time.Millisecond})
	s, err := c.Standing()
	if err != nil {
		t.Fatal(err)
	}
	live := as(t, c, bus.Client)
	answered := make(chan error, 1)
	go func() {
		m, err := live.Request(bus.Call+bus.Token("kept run"), []byte(`{"args": ["live"]}`), time.Minute)
		if err == nil {
			var a host.CallAnswer
			if err = json.Unmarshal(m.Data, &a); err == nil && (a.Error != "" || a.Text != "let go live") {
				err = fmt.Errorf("the live call answers %+v", a)
			}
		}
		answered <- err
	}()
	cmd := exec.Command(os.Args[0], "-test.run=^$", "dead", callerArg)
	cmd.Env = append(os.Environ(), bus.EnvBus+"="+s.Bus, bus.EnvToken+"="+s.Users[bus.Client])
	out, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = cmd.Process.Kill(); _ = cmd.Wait() })
	if line, _ := bufio.NewReader(out).ReadString('\n'); strings.TrimSpace(line) != "calling" {
		t.Fatalf("the caller's process says %q", line)
	}
	for asked := map[string]bool{}; !asked["live"] || !asked["dead"]; {
		select {
		case word := <-held:
			asked[word] = true
		case <-time.After(wait):
			t.Fatalf("the keeper holds %v, and wants both calls", asked)
		}
	}
	select {
	case err := <-gone:
		t.Fatalf("a call is given up while both callers live: %v", err)
	case <-time.After(200 * time.Millisecond):
	}
	if err := cmd.Process.Kill(); err != nil {
		t.Fatal(err)
	}
	killed := time.Now()
	select {
	case err := <-gone:
		if !errors.Is(err, host.ErrCallerGone) || !strings.HasPrefix(err.Error(), "dead: ") {
			t.Fatalf("the keeper lets go of %v, and wants the killed caller's call given up as gone", err)
		}
		if since := time.Since(killed); since > host.LeaseLapse {
			t.Fatalf("the killed caller's call is given up after %v, beyond the lease lapse %v", since, host.LeaseLapse)
		}
	case <-time.After(host.LeaseLapse + wait):
		t.Fatal("the killed caller's call runs on")
	}
	close(release)
	select {
	case err := <-answered:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(wait):
		t.Fatal("the live call beside it does not answer")
	}
}
