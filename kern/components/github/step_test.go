package github_test

import (
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/kern/bus"
	"github.com/mb-89/kern/cli"
	"github.com/mb-89/kern/components/github"
	"github.com/mb-89/kern/host"
	"github.com/mb-89/kern/index"
)

// stepper is another component whose command `run <tool> <input JSON>` runs
// one tool call through the verb step and shows the input the session sent
// and the answer; a second step follows where the input names "then".
var stepper = func() *index.Component {
	step := index.JSONRequest("step", "Runs one GitHub tool call.", github.StepShape, github.StepAnswerShape)
	var run func(args []string) (index.Result, error)
	run = func(args []string) (index.Result, error) {
		var in map[string]any
		if err := json.Unmarshal([]byte(args[1]), &in); err != nil {
			return index.Result{}, err
		}
		ask := github.StepAsk{Tool: args[0], Input: in, Note: "note " + args[0], Wait: "10s"}
		return index.Result{Requests: []index.Ask{step.Ask(ask)}, Then: func(a []any) (index.Result, error) {
			var got github.StepAnswer
			if err := index.Recode(step.Answer(a[0]), &got); err != nil {
				return index.Result{}, err
			}
			sent, _ := json.Marshal(got.Input)
			data, _ := json.Marshal(got.Data)
			r := index.Result{Text: string(sent) + " -> " + string(data)}
			if next, ok := in["then"].(string); ok {
				more, err := run([]string{next, `{"owner": "alice", "repo": "demo", "issue_number": 7}`})
				if err != nil {
					return r, err
				}
				more.Text = r.Text
				return more, nil
			}
			return r, nil
		}}, nil
	}
	return index.Declare("stepper", "Runs tool calls through the github component.", step,
		index.Command(index.CommandDecl{
			Name: "run", Usage: "run TOOL INPUT", Summary: "Run one tool call.", Help: "Shows its answer.",
			Group: "Fixtures", Class: index.Batch,
		}, func(_ struct{}, args []string) (index.Result, error) { return run(args) }),
	)
}()

func stepWiring(t *testing.T, config string) index.Wiring {
	t.Helper()
	w, err := index.ParseWiring([]byte(`
[instances.github]
component = "github"
config = { ` + config + ` }

[instances.stepper]
component = "stepper"

[wires]
"github.outbox" = "github/outbox/<key>"
"stepper.step" = "github.step"
`))
	if err != nil {
		t.Fatal(err)
	}
	return w
}

func startedSteps(t *testing.T, o github.Options, config string) (*github.GitHub, *index.Index) {
	t.Helper()
	g := github.New(o)
	ix, err := index.Start(stepWiring(t, config), g.Component, stepper)
	if err != nil {
		t.Fatal(err)
	}
	return g, ix
}

// waitOutbox waits until the relay tells a step, and answers what it tells.
func waitOutbox(t *testing.T, g *github.GitHub, has string) string {
	t.Helper()
	end := time.Now().Add(10 * time.Second)
	for time.Now().Before(end) {
		if text := g.Outbox(); strings.Contains(text, has) {
			return text
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatalf("the outbox never told %q; it tells %q", has, g.Outbox())
	return ""
}

type called struct {
	r   index.Result
	err error
}

func call(ix *index.Index, args ...string) chan called {
	done := make(chan called, 1)
	go func() {
		r, err := ix.Call("run", args...)
		done <- called{r, err}
	}()
	return done
}

// A step stands in the outbox until the PostToolUse of that tool with those
// arguments answers it: another number, another tool or a Bash call leaves it
// waiting; the session may add arguments and change a long body, and the
// answer carries the input it sent.
func TestAStepWaitsForTheToolUseThatMatchesIt(t *testing.T) {
	t.Parallel()
	g, ix := startedSteps(t, github.Options{Now: (&clock{now: nine}).Now, Token: noToken}, ``)
	body := strings.Repeat("a body line\n", 40)
	in, _ := json.Marshal(map[string]any{"owner": "alice", "repo": "demo", "pullNumber": 8, "merge_method": "squash", "commit_message": body})
	done := call(ix, "merge_pull_request", string(in))
	told := waitOutbox(t, g, "merge_pull_request")
	if !strings.Contains(told, `1. merge_pull_request {"commit_message":`) || !strings.Contains(told, "   note merge_pull_request") {
		t.Fatalf("the relay tells %q", told)
	}
	if v, _ := ix.Read("github/outbox/" + strings.Fields(strings.SplitN(told, "\n", 2)[1])[0]); v.Provided {
		t.Fatal("an outbox key reads as a tool name")
	}
	for _, p := range [][]byte{
		toolUse("mcp__github__merge_pull_request", map[string]any{"owner": "alice", "repo": "demo", "pullNumber": 9, "merge_method": "squash"}, `{"merged": true}`),
		toolUse("mcp__github__update_pull_request", map[string]any{"owner": "alice", "repo": "demo", "pullNumber": 8, "merge_method": "squash"}, `{}`),
		toolUse("Bash", map[string]any{"command": "ls"}, `{}`),
	} {
		if err := ix.Hear(github.PostToolUse, p); err != nil {
			t.Fatal(err)
		}
	}
	select {
	case c := <-done:
		t.Fatalf("the step is answered by another call: %+v", c)
	case <-time.After(200 * time.Millisecond):
	}
	if err := ix.Hear(github.PostToolUse, toolUse("mcp__0f1e__merge_pull_request",
		map[string]any{"owner": "Alice", "repo": "demo", "pullNumber": "8", "merge_method": "squash", "commit_message": "edited", "commit_title": "t"},
		`{"sha": "abc", "merged": true}`)); err != nil {
		t.Fatal(err)
	}
	c := <-done
	if c.err != nil || c.r.Text != `{"commit_message":"edited","commit_title":"t","merge_method":"squash","owner":"Alice","pullNumber":"8","repo":"demo"} -> {"merged":true,"sha":"abc"}` {
		t.Fatalf("the step answers %q, %v", c.r.Text, c.err)
	}
}

// The matching answer: its input as sent, its JSON as JSON, a text that is
// no JSON as its text, and an error answer as the step's failure.
func TestAStepAnswersTheToolsAnswer(t *testing.T) {
	t.Parallel()
	g, ix := startedSteps(t, github.Options{Now: (&clock{now: nine}).Now, Token: noToken}, ``)
	done := call(ix, "add_issue_comment", `{"owner": "alice", "repo": "demo", "issue_number": 7, "body": "Landed.", "then": "issue_write"}`)
	waitOutbox(t, g, "add_issue_comment")
	if err := ix.Hear(github.PostToolUse, toolUse("mcp__github__add_issue_comment",
		map[string]any{"owner": "alice", "repo": "demo", "issue_number": 7, "body": "Landed.", "then": "issue_write", "extra": true}, `{"id": 5}`)); err != nil {
		t.Fatal(err)
	}
	waitOutbox(t, g, "issue_write")
	if err := ix.Hear(github.PostToolUse, toolUse("mcp__github__issue_write",
		map[string]any{"owner": "alice", "repo": "demo", "issue_number": 7}, "Issue updated")); err != nil {
		t.Fatal(err)
	}
	c := <-done
	want := `{"body":"Landed.","extra":true,"issue_number":7,"owner":"alice","repo":"demo","then":"issue_write"} -> {"id":5}` + "\n" +
		`{"issue_number":7,"owner":"alice","repo":"demo"} -> "Issue updated"`
	if c.err != nil || c.r.Text != want {
		t.Fatalf("the steps answer %q, %v, and want %q", c.r.Text, c.err, want)
	}
	if g.Outbox() != "" {
		t.Fatalf("answered steps stand in the outbox: %q", g.Outbox())
	}

	done = call(ix, "issue_write", `{"owner": "alice", "repo": "demo", "issue_number": 7}`)
	waitOutbox(t, g, "issue_write")
	if err := ix.Hear(github.PostToolUse, []byte(`{"tool_name": "mcp__github__issue_write", "tool_input": {"owner": "alice", "repo": "demo", "issue_number": 7},
		"tool_response": {"content": [{"type": "text", "text": "Resource not accessible"}], "isError": true}}`)); err != nil {
		t.Fatal(err)
	}
	if c := <-done; c.err == nil || !strings.Contains(c.err.Error(), "the tool answered an error: Resource not accessible") {
		t.Fatalf("an error answer gives %+v", c)
	}
}

// Only the relay runs steps; a step without a tool or input is refused.
func TestOnlyTheRelayRunsSteps(t *testing.T) {
	t.Parallel()
	_, ix := startedSteps(t, github.Options{Now: (&clock{now: nine}).Now, Token: token(""), Cloud: notCloud}, ``)
	if _, err := ix.Call("run", "merge_pull_request", `{"owner": "alice"}`); err == nil || !strings.Contains(err.Error(), `the backend is "token": only the relay runs`) {
		t.Fatalf("a step through the token answers %v", err)
	}
	_, ix = startedSteps(t, github.Options{Now: (&clock{now: nine}).Now, Token: noToken}, ``)
	if _, err := ix.Call("run", "mcp__github__merge_pull_request", `{}`); err == nil || !strings.Contains(err.Error(), "the tool's bare name") {
		t.Fatalf("a step named with its server answers %v", err)
	}
}

// The tell of a PostToolUse that answered a step waits for the next step and
// tells it; one that answered none tells what waits at once; other events tell
// nothing.
func TestTheHookOfAnAnswerTellsTheNextStep(t *testing.T) {
	t.Parallel()
	g, ix := startedSteps(t, github.Options{Now: (&clock{now: nine}).Now, Token: noToken}, `tell-wait = "10s"`)
	done := call(ix, "add_issue_comment", `{"owner": "alice", "repo": "demo", "issue_number": 7, "body": "x", "then": "issue_write"}`)
	waitOutbox(t, g, "add_issue_comment")
	if said := ix.Tell("Stop", nil); len(said) != 0 {
		t.Fatalf("a Stop is told %q", said)
	}
	if said := ix.Tell("UserPromptSubmit", nil); len(said) != 1 || !strings.Contains(said[0], "1. add_issue_comment") {
		t.Fatalf("a prompt is told %q", said)
	}
	answer := toolUse("mcp__github__add_issue_comment", map[string]any{"owner": "alice", "repo": "demo", "issue_number": 7, "body": "x", "then": "issue_write"}, `{}`)
	if err := ix.Hear(github.PostToolUse, answer); err != nil {
		t.Fatal(err)
	}
	said := ix.Tell(github.PostToolUse, answer)
	if len(said) != 1 || !strings.Contains(said[0], "1. issue_write") || strings.Contains(said[0], "add_issue_comment") {
		t.Fatalf("the answer's hook tells %q, and wants the next step", said)
	}
	_ = ix.Hear(github.PostToolUse, toolUse("mcp__github__issue_write", map[string]any{"owner": "alice", "repo": "demo", "issue_number": 7}, `{}`))
	<-done
}

// Through the real core and the command line: the hook of a tool answer
// prints the next step as the host's hook JSON, which hands it the agent.
func TestAHookPrintsTheRelaysStepsAsContext(t *testing.T) {
	t.Parallel()
	g := github.New(github.Options{Now: (&clock{now: nine}).Now, Token: noToken})
	c, err := host.Serve(host.Options{Root: t.TempDir(), Wiring: stepWiring(t, ``), Components: []*index.Component{g.Component, stepper}})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { c.Stop("the case ends"); <-c.Ended() })
	s, _ := c.Standing()
	nc, err := bus.Dial(s.Bus, bus.Client, s.Users[bus.Client])
	if err != nil {
		t.Fatal(err)
	}
	defer nc.Close()
	go func() {
		_, _ = nc.Request(bus.Call+"run", []byte(`{"args": ["merge_pull_request", "{\"owner\": \"alice\", \"repo\": \"demo\", \"pullNumber\": 8}"]}`), 20*time.Second)
	}()
	waitOutbox(t, g, "merge_pull_request")
	a, err := host.Post(host.Wall{}, s.Root, "UserPromptSubmit", []byte(`{"session_id": "s1"}`), 10*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	var out struct {
		Specific struct {
			Event   string `json:"hookEventName"`
			Context string `json:"additionalContext"`
		} `json:"hookSpecificOutput"`
	}
	if err := json.Unmarshal(cli.HookOutput("UserPromptSubmit", a), &out); err != nil || out.Specific.Event != "UserPromptSubmit" ||
		!strings.Contains(out.Specific.Context, `1. merge_pull_request {"owner":"alice","pullNumber":8,"repo":"demo"}`) {
		t.Fatalf("the hook prints %s (%v)", cli.HookOutput("UserPromptSubmit", a), err)
	}
	if cli.HookOutput("Stop", a) != nil || cli.HookOutput("PostToolUse", host.HookAnswer{Effect: "pass"}) != nil {
		t.Fatal("a Stop, or an answer with nothing told, prints hook output")
	}
	_, _ = host.Post(host.Wall{}, s.Root, github.PostToolUse, toolUse("mcp__github__merge_pull_request", map[string]any{"owner": "alice", "repo": "demo", "pullNumber": 8}, `{}`), 10*time.Second)
}
