package contract

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/kern/bus"
	"github.com/mb-89/kern/cli"
	"github.com/mb-89/kern/host"
	"github.com/mb-89/kern/index"
	"github.com/nats-io/nats.go"
)

// placeDrip writes drip's folder and a wiring that places it in its own Python
// process under root.
func placeDrip(t *testing.T, root string) {
	t.Helper()
	dir := filepath.Join(root, "components", "drip")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	for _, f := range []string{index.DeclarationFile, "__init__.py"} {
		data, err := os.ReadFile(filepath.Join("fixture", "drip", f))
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(dir, f), data, 0o600); err != nil {
			t.Fatal(err)
		}
	}
	command, _ := json.Marshal([]string{pythonPath(t), "-m", "kern", "run", "components/drip"})
	wiring := fmt.Sprintf("[instances.drip]\ncomponent = \"drip\"\ncommand = %s\n", command)
	if err := os.WriteFile(filepath.Join(root, index.WiringFile), []byte(wiring), 0o600); err != nil {
		t.Fatal(err)
	}
}

// The real core with drip in its own Python process and the bus's reply wait
// lowered to 1 s (cli.ReplyWaitEnv), where the step wait is 30 s: a step that
// answers after its reply permission ran out is refused by the bus, and the
// runner says so, so the call fails at once, naming the refusal, and never
// waits out the step wait in silence. Without the bound, as kern serves, the
// same answer lands (TestAStepAnswersAfterALongLocalPhase, the long one,
// holds that against NATS's own two minutes).
func TestAStepAnswerTheBusRefusesFailsTheCallAtOnce(t *testing.T) {
	root := checkout(t)
	placeDrip(t, root)
	env := []string{"PYTHONPATH=" + sdk(t), "PYTHONDONTWRITEBYTECODE=1", cli.StepWaitEnv + "=30s", cli.ReplyWaitEnv + "=1s"}
	want(t, run(t, env, "start", "--root", root), 0, "kern: started")
	want(t, run(t, nil, "status", "--root", root, "--wait", wait), 0, "kern: running")
	s := standing(t, root)
	client, err := bus.Dial(s.Bus, bus.Client, s.Users[bus.Client])
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(client.Close)

	began := time.Now()
	m, err := client.Request(bus.Call+bus.Token("drip quiet"), []byte(`{"args":["1.5"]}`), 60*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	var a host.CallAnswer
	if err := json.Unmarshal(m.Data, &a); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(a.Error, "the bus refused its answer") || !strings.Contains(a.Error, "Permissions Violation") {
		t.Fatalf("drip quiet, answering past its reply wait, answers %+v, and wants the refusal named", a)
	}
	if took := time.Since(began); took > 20*time.Second {
		t.Fatalf("the refused answer failed the call after %v: it waited for the step wait of 30 s", took)
	}
	m, err = client.Request(bus.Call+bus.Token("drip quiet"), []byte(`{"args":["0.2"]}`), 60*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	var quick host.CallAnswer
	if err := json.Unmarshal(m.Data, &quick); err != nil || quick.Error != "" || quick.Text != "slept" {
		t.Fatalf("drip quiet within its reply wait answers %+v (%v)", quick, err)
	}
}

// The real core with drip placed in its own Python process and the core's
// step wait lowered to 1 s: a step that talks outlives it, as each line
// restarts the wait; one that stays silent past it fails, naming the wait. A
// streaming caller hears every line, in order, before the one answer.
func TestARealStepThatTalksOutlivesTheStepWaitAndStreamsToItsCaller(t *testing.T) {
	root := checkout(t)
	placeDrip(t, root)
	env := []string{"PYTHONPATH=" + sdk(t), "PYTHONDONTWRITEBYTECODE=1", cli.StepWaitEnv + "=1s"}
	want(t, run(t, env, "start", "--root", root), 0, "kern: started")
	want(t, run(t, nil, "status", "--root", root, "--wait", wait), 0, "kern: running")
	s := standing(t, root)
	client, err := bus.Dial(s.Bus, bus.Client, s.Users[bus.Client])
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(client.Close)

	inbox := bus.Inbox(bus.Client) + ".drip"
	progress, reply := inbox+".progress", inbox+".reply"
	heard := make(chan *nats.Msg, 64)
	for _, subj := range []string{progress, reply} {
		if _, err := client.ChanSubscribe(subj, heard); err != nil {
			t.Fatal(err)
		}
	}
	body, _ := json.Marshal(map[string]any{"args": []string{"8"}, "progress": progress})
	if err := client.PublishRequest(bus.Call+bus.Token("drip talk"), reply, body); err != nil {
		t.Fatal(err)
	}
	var lines []string
	var a host.CallAnswer
	deadline := time.After(30 * time.Second)
	for done := false; !done; {
		select {
		case m := <-heard:
			if m.Subject == reply {
				if err := json.Unmarshal(m.Data, &a); err != nil {
					t.Fatal(err)
				}
				done = true
				continue
			}
			var p host.Progress
			if err := json.Unmarshal(m.Data, &p); err != nil {
				t.Fatal(err)
			}
			if p.Line != "" {
				lines = append(lines, p.Line)
			}
		case <-deadline:
			t.Fatalf("drip talk answers nothing; it said %q", lines)
		}
	}
	want8 := []string{}
	for i := 1; i <= 8; i++ {
		want8 = append(want8, fmt.Sprintf("tick %d", i))
	}
	if a.Error != "" || a.Text != "said 8 lines" {
		t.Fatalf("drip talk, two seconds against a step wait of one, answers %+v", a)
	}
	if strings.Join(lines, "|") != strings.Join(want8, "|") || strings.Join(a.Lines, "|") != strings.Join(want8, "|") {
		t.Fatalf("the caller heard %q and the answer holds %q, and both want %q in order", lines, a.Lines, want8)
	}

	m, err := client.Request(bus.Call+bus.Token("drip quiet"), []byte(`{"args":["2.5"]}`), 30*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	var quiet host.CallAnswer
	if err := json.Unmarshal(m.Data, &quiet); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(quiet.Error, "no answer, line or beat within 1s") {
		t.Fatalf("drip quiet, silent past the step wait, answers %+v, and wants the wait named", quiet)
	}
}
