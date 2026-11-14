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

const quietDeclaration = `name = "quiet"
contract = 1
help = "Answers a step the bus refuses."

[commands."quiet on"]
usage = "quiet on"
summary = "Answer late."
group = "Fixtures"
help = "Its answer is refused by the bus."
class = "batch"
`

// The fast guard of the long step (contract/longstep_test.go, beside the
// suite): where the runner says the bus refused its answer, {"refused"} on
// say.<i>.<call>, the core fails the step at once, naming the refusal, and
// never waits out its step wait of a minute in silence.
func TestAStepWhoseAnswerTheBusRefusedFailsAtOnce(t *testing.T) {
	t.Parallel()
	root := t.TempDir()
	dir := filepath.Join(root, "components", "quiet")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, index.DeclarationFile), []byte(quietDeclaration), 0o600); err != nil {
		t.Fatal(err)
	}
	w, err := index.ParseWiring([]byte("[instances.quiet]\ncomponent = \"quiet\"\n"))
	if err != nil {
		t.Fatal(err)
	}
	c := served(t, host.Options{Root: root, Clock: newClock(), Wiring: w, StepWait: time.Minute})
	proc := as(t, c, "quiet")
	steps := make(chan *nats.Msg, 8)
	if _, err := proc.ChanSubscribe(bus.Cmd+"quiet.>", steps); err != nil {
		t.Fatal(err)
	}
	var attached map[string]any
	ask(t, proc, bus.Commit+"quiet", map[string]any{"attach": host.Attach{Contract: host.Contract, Hash: index.Hash([]byte(quietDeclaration))}}, &attached)
	if attached["accepted"] != true {
		t.Fatalf("the attach answers %v", attached)
	}
	client := as(t, c, bus.Client)
	reply := bus.Inbox(bus.Client) + ".quiet"
	answered := make(chan *nats.Msg, 1)
	if _, err := client.ChanSubscribe(reply, answered); err != nil {
		t.Fatal(err)
	}
	if err := client.PublishRequest(bus.Call+bus.Token("quiet on"), reply, []byte(`{"args":[]}`)); err != nil {
		t.Fatal(err)
	}
	var step *nats.Msg
	select {
	case step = <-steps:
	case <-time.After(wait):
		t.Fatal("the process hears nothing on cmd.quiet.>")
	}
	var s index.Step
	if err := json.Unmarshal(step.Data, &s); err != nil || s.Call == "" {
		t.Fatalf("the step reads %s", step.Data)
	}
	why := `Permissions Violation for Publish to "` + step.Reply + `"`
	data, _ := json.Marshal(map[string]string{"refused": why})
	if err := proc.Publish(bus.Say+"quiet."+bus.Token(s.Call), data); err != nil {
		t.Fatal(err)
	}
	select {
	case m := <-answered:
		var a host.CallAnswer
		if err := json.Unmarshal(m.Data, &a); err != nil || !strings.Contains(a.Error, "the bus refused its answer") ||
			!strings.Contains(a.Error, why) {
			t.Fatalf("the call whose answer the bus refused answers %s, and wants the refusal named", m.Data)
		}
	case <-time.After(wait):
		t.Fatalf("the call whose answer the bus refused answers nothing within %v: it waits out its step wait", wait)
	}
}
