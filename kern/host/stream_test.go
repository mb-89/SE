package host_test

import (
	"encoding/json"
	"os"
	"path/filepath"
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

// A caller gives up its own call on call.core.abandon, naming it by its reply
// subject: the call answers its error at once, naming why, while a call of
// the same command beside it runs to its end. A call in another inbox is
// refused, and one that no longer runs answers that none was given up.
func TestACallerGivesUpItsOwnCallAndTheCallBesideItRunsOn(t *testing.T) {
	t.Parallel()
	w, comps, release := slowWiring(t)
	c := served(t, host.Options{Clock: newClock(), Wiring: w, Components: comps})
	client := as(t, c, bus.Client)
	inbox := bus.Inbox(bus.Client) + ".case"
	heard := make(chan *nats.Msg, 16)
	for _, reply := range []string{inbox + ".a", inbox + ".b"} {
		if _, err := client.ChanSubscribe(reply, heard); err != nil {
			t.Fatal(err)
		}
		body, _ := json.Marshal(map[string]any{"args": []string{reply[len(reply)-1:]}})
		if err := client.PublishRequest(bus.Call+bus.Token("long run"), reply, body); err != nil {
			t.Fatal(err)
		}
	}
	var refused host.Abandoned
	ask(t, client, host.AbandonSubject, host.Abandon{Call: "_INBOX.other.a"}, &refused)
	if refused.Abandoned || !strings.Contains(refused.Error, "outside the asker's inbox") {
		t.Fatalf("giving up a call in another inbox answers %+v, and wants it refused", refused)
	}
	var given host.Abandoned
	ask(t, client, host.AbandonSubject, host.Abandon{Call: inbox + ".a"}, &given)
	if !given.Abandoned || given.Error != "" {
		t.Fatalf("giving up the running call answers %+v", given)
	}
	answer := func() (string, host.CallAnswer) {
		t.Helper()
		select {
		case m := <-heard:
			var a host.CallAnswer
			if err := json.Unmarshal(m.Data, &a); err != nil {
				t.Fatal(err)
			}
			return m.Subject, a
		case <-time.After(wait):
			t.Fatal("no call answers")
		}
		return "", host.CallAnswer{}
	}
	subject, a := answer()
	if subject != inbox+".a" || !strings.Contains(a.Error, "the call is given up: its caller gave it up") {
		t.Fatalf("%s answers %+v first, and wants the given-up call's error, before its verb lets go", subject, a)
	}
	close(release)
	subject, a = answer()
	if subject != inbox+".b" || a.Error != "" || a.Text != "let go b" {
		t.Fatalf("%s answers %+v, and wants the call beside it to run to its end", subject, a)
	}
	var gone host.Abandoned
	ask(t, client, host.AbandonSubject, host.Abandon{Call: inbox + ".b"}, &gone)
	if gone.Abandoned || gone.Error != "" {
		t.Fatalf("giving up a call that ended answers %+v, and wants none given up", gone)
	}
}

// heldDeclaration is a declared component whose command asks the desk once
// and answers in its continuation; the case plays its process.
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

// A call to a declared component that its caller gives up while the request
// of its first step waits: the core tells the process on the command's
// cmd.<i>.<command>, without a reply, {"call", "stop"}, naming the call and
// why, so the continuation the process holds for it ends.
func TestTheCoreTellsTheProcessOnItsStopWordThatACallIsGivenUp(t *testing.T) {
	t.Parallel()
	root := t.TempDir()
	dir := filepath.Join(root, "components", "held")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, index.DeclarationFile), []byte(heldDeclaration), 0o600); err != nil {
		t.Fatal(err)
	}
	release := make(chan struct{})
	t.Cleanup(func() { close(release) })
	desk := index.Declare("desk", "Answers questions.", index.IO(),
		index.Verb("answer", "Answers once the case lets it go.", func(q string) (string, error) {
			<-release
			return "yes " + q, nil
		}))
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
	c := served(t, host.Options{Root: root, Clock: newClock(), Wiring: w, Components: []*index.Component{desk}})
	proc := as(t, c, "held")
	steps := make(chan *nats.Msg, 8)
	if _, err := proc.ChanSubscribe(bus.Cmd+"held.>", steps); err != nil {
		t.Fatal(err)
	}
	var attached map[string]any
	ask(t, proc, bus.Commit+"held", map[string]any{"attach": host.Attach{Contract: host.Contract, Hash: index.Hash([]byte(heldDeclaration))}}, &attached)
	if attached["accepted"] != true {
		t.Fatalf("the attach answers %v", attached)
	}
	client := as(t, c, bus.Client)
	reply := bus.Inbox(bus.Client) + ".held"
	answered := make(chan *nats.Msg, 1)
	if _, err := client.ChanSubscribe(reply, answered); err != nil {
		t.Fatal(err)
	}
	if err := client.PublishRequest(bus.Call+bus.Token("held on"), reply, []byte(`{"args":["a"]}`)); err != nil {
		t.Fatal(err)
	}
	next := func() *nats.Msg {
		t.Helper()
		select {
		case m := <-steps:
			return m
		case <-time.After(wait):
			t.Fatal("the process hears nothing on cmd.held.>")
		}
		return nil
	}
	first := next()
	var s index.Step
	if err := json.Unmarshal(first.Data, &s); err != nil || s.Step != 1 || first.Reply == "" {
		t.Fatalf("the first step reads %s, reply %q", first.Data, first.Reply)
	}
	data, _ := json.Marshal(index.Answer{Requests: []index.WireAsk{{Port: "ask", Value: json.RawMessage(`"a"`)}}, Then: true})
	if err := first.Respond(data); err != nil {
		t.Fatal(err)
	}
	var given host.Abandoned
	ask(t, client, host.AbandonSubject, host.Abandon{Call: reply}, &given)
	if !given.Abandoned {
		t.Fatalf("giving up the running call answers %+v", given)
	}
	stop := next()
	var word host.StopWord
	if err := json.Unmarshal(stop.Data, &word); err != nil {
		t.Fatal(err)
	}
	if stop.Reply != "" || stop.Subject != bus.Cmd+"held."+bus.Token("held on") || word.Call != s.Call ||
		!strings.Contains(word.Stop, "its caller gave it up") {
		t.Fatalf("the process hears %s %s (reply %q), and wants the stop word of call %s", stop.Subject, stop.Data, stop.Reply, s.Call)
	}
	select {
	case m := <-answered:
		var a host.CallAnswer
		if err := json.Unmarshal(m.Data, &a); err != nil || !strings.Contains(a.Error, "given up") {
			t.Fatalf("the given-up call answers %s", m.Data)
		}
	case <-time.After(wait):
		t.Fatal("the given-up call answers nothing")
	}
}
