package host_test

import (
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/kern/bus"
	"github.com/mb-89/kern/host"
	"github.com/mb-89/kern/index"
	"github.com/nats-io/nats.go"
)

// slow is a command of two steps: the first says a line and asks the slow I/O
// verb, which holds until the case lets it go; the second says the answer.
func slowWiring(t *testing.T) (index.Wiring, []*index.Component, chan struct{}) {
	t.Helper()
	release := make(chan struct{})
	hold := index.Request[string, string]("hold", "Waits until the case lets it go.")
	holder := index.Declare("holder", "Holds a request.", index.IO(),
		index.Verb("hold", "Waits until the case lets it go.", func(s string) (string, error) {
			<-release
			return "let go " + s, nil
		}))
	runner := index.Declare("runner", "Runs a long command.", hold,
		index.Command(index.CommandDecl{
			Name: "long run", Usage: "long run WORD", Summary: "Run long.", Help: "Says a line, waits, says the answer.",
			Group: "Fixtures", Class: index.Batch,
		}, func(_ struct{}, args []string) (index.Result, error) {
			return index.Result{Lines: []string{"Phase: holding " + args[0]}, Requests: []index.Ask{hold.Ask(args[0])},
				Then: func(a []any) (index.Result, error) {
					return index.Result{Lines: []string{"Phase: answered"}, Text: a[0].(string)}, nil
				}}, nil
		}))
	w, err := index.ParseWiring([]byte(`
[instances.holder]
component = "holder"

[instances.runner]
component = "runner"

[wires]
"runner.hold" = "holder.hold"
`))
	if err != nil {
		t.Fatal(err)
	}
	return w, []*index.Component{holder, runner}, release
}

// A call that names a progress subject in its caller's inbox hears each line
// as its step says it and a beat every CallBeat while the call runs, before
// its one answer, which still holds every line: the caller waits as long as
// the core says anything, not a fixed time.
func TestAStreamingCallHearsItsLinesAndBeatsBeforeItsAnswer(t *testing.T) {
	t.Parallel()
	w, comps, release := slowWiring(t)
	c := served(t, host.Options{Clock: newClock(), Wiring: w, Components: comps, CallBeat: 10 * time.Millisecond})
	client := as(t, c, bus.Client)
	inbox := bus.Inbox(bus.Client) + ".case"
	progress, reply := inbox+".progress", inbox+".reply"
	heard := make(chan *nats.Msg, 256)
	for _, subj := range []string{progress, reply} {
		if _, err := client.ChanSubscribe(subj, heard); err != nil {
			t.Fatal(err)
		}
	}
	body, _ := json.Marshal(map[string]any{"args": []string{"x"}, "progress": progress})
	if err := client.PublishRequest(bus.Call+bus.Token("long run"), reply, body); err != nil {
		t.Fatal(err)
	}
	var lines []string
	beats := 0
	for answered := false; !answered; {
		select {
		case m := <-heard:
			if m.Subject == reply {
				if beats < 2 || strings.Join(lines, "|") != "Phase: holding x|Phase: answered" {
					t.Fatalf("the answer came after %d beats and the lines %q, and wants two beats and both lines, in order, before it", beats, lines)
				}
				var a host.CallAnswer
				if err := json.Unmarshal(m.Data, &a); err != nil {
					t.Fatal(err)
				}
				if a.Error != "" || a.Text != "let go x" || strings.Join(a.Lines, "|") != "Phase: holding x|Phase: answered" {
					t.Fatalf("the call answers %+v", a)
				}
				answered = true
				continue
			}
			var p host.Progress
			if err := json.Unmarshal(m.Data, &p); err != nil {
				t.Fatal(err)
			}
			if p.Line != "" {
				lines = append(lines, p.Line)
			} else if p.Beat {
				beats++
				if beats == 2 {
					close(release) // the held verb answers once the caller heard it beat twice
				}
			}
		case <-time.After(wait):
			t.Fatalf("the call says nothing more after %d beats and the lines %q", beats, lines)
		}
	}
}

// A progress subject outside the caller's own inbox is refused before the
// command runs, so no caller streams onto another's subjects.
func TestAProgressSubjectOutsideTheCallersInboxIsRefused(t *testing.T) {
	t.Parallel()
	w, comps, release := slowWiring(t)
	close(release)
	c := served(t, host.Options{Clock: newClock(), Wiring: w, Components: comps})
	client := as(t, c, bus.Client)
	var a host.CallAnswer
	ask(t, client, bus.Call+bus.Token("long run"), map[string]any{"args": []string{"x"}, "progress": "cmd.runner.long"}, &a)
	if !strings.Contains(a.Error, "outside the caller's inbox") || a.Text != "" {
		t.Fatalf("the call answers %+v, and wants the progress subject refused", a)
	}
	var plain host.CallAnswer
	ask(t, client, bus.Call+bus.Token("long run"), map[string]any{"args": []string{"y"}}, &plain)
	if plain.Error != "" || plain.Text != "let go y" {
		t.Fatalf("a call without progress answers %+v", plain)
	}
}
