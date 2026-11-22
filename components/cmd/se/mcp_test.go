package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	sdk "github.com/modelcontextprotocol/go-sdk/mcp"
	"kern/cli"
	"kern/host"
	"kern/index"
	"kern/mcp"
)

// SE's own catalog, its root wiring.toml and its components' declarations as
// the core reads them, passes the MCP door's catalog check, and makes a few
// coarse tools: status, the greeting with every part it reads, and one per
// command group that offers commands declared read-only; work_tickets.py
// queue, which syncs the checkout, is in none.
func TestSEsCatalogMakesTheDoorsTools(t *testing.T) {
	root := filepath.Join("..", "..", "..")
	w, err := cli.Wiring(root)
	if err != nil {
		t.Fatal(err)
	}
	c, err := host.Catalog(root, w, index.Registered())
	if err != nil {
		t.Fatal(err)
	}
	tools, err := mcp.Tools("se", c, Greeting)
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, tool := range tools {
		names = append(names, tool.Name)
		if tool.Name == mcp.GreetingTool && len(tool.Greeting) != len(Greeting) {
			t.Errorf("the greeting reads %+v, and wants every part of %v", tool.Greeting, Greeting)
		}
		for _, c := range tool.Commands {
			if c.Name == "work_tickets.py queue" {
				t.Errorf("tool %s offers work_tickets.py queue, which syncs the checkout", tool.Name)
			}
		}
	}
	if got := strings.Join(names, " "); got != "status greeting integration overhaul templates tickets" || len(tools) < 3 || len(tools) > 8 {
		t.Fatalf("SE's door offers the tools %q, and wants status, greeting, integration, overhaul, templates and tickets", got)
	}
}

// The door's contract, the one test with a real MCP client (the Go SDK's)
// against the built `se mcp` and the real core it starts, once per handshake:
// server/discover of the MCP spec of 2026-07-28, which the client sends first,
// and the legacy initialize of a client that knows only 2025-11-25. Each
// handshake and tools/list answer while the core's start is held, from a cold
// start (a fresh `se mcp`, no core running), and the test logs how long the
// first answer took; status answers once the core runs with the door's
// session holding a lease; the core stopped with se stop is started again by
// the next call, before the door's renewal; and the core ends its grace after
// the client hangs up.
func TestTheMCPDoorStartsTheCoreAndEndsItWithTheSession(t *testing.T) {
	dir := t.TempDir()
	se := filepath.Join(dir, "se")
	if runtime.GOOS == "windows" {
		se += ".exe"
	}
	build := exec.Command("go", "build", "-o", se, ".")
	if out, err := build.CombinedOutput(); err != nil {
		t.Fatalf("go build of cmd/se: %v\n%s", err, out)
	}
	for _, c := range []struct{ name, asks, wants string }{
		{"server-discover", "", "2026-07-28"},
		{"initialize", "2025-11-25", "2025-11-25"},
	} {
		t.Run(c.name, func(t *testing.T) { doorContract(t, se, c.asks, c.wants) })
	}
}

// doorContract runs the contract with a client that asks the protocol asks
// (empty: the SDK's newest, by server/discover) and wants the door to answer
// wants.
func doorContract(t *testing.T, se, asks, wants string) {
	dir := t.TempDir()
	root := t.TempDir()
	if err := os.Mkdir(filepath.Join(root, ".git"), 0o700); err != nil {
		t.Fatal(err)
	}
	// A declared component whose read-only command the door offers as a tool;
	// no process runs it, as the tool list needs none.
	desk := filepath.Join(root, "components", "desk")
	if err := os.MkdirAll(desk, 0o700); err != nil {
		t.Fatal(err)
	}
	write := func(path, text string) {
		t.Helper()
		if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	write(filepath.Join(desk, index.DeclarationFile), `name = "desk"
contract = 1
help = "The desk: what waits on it."

[commands."desk list"]
usage = "desk list"
summary = "list the desk"
group = "Desk"
help = "list the desk"
class = "interactive"
read-only = true
mcp = "Lists what waits on the desk; use it to see what to do next."
`)
	write(filepath.Join(root, index.WiringFile), "[instances.desk]\ncomponent = \"desk\"\n")
	// git reaches only the door's fake (kern/git): a repository with no refs.
	state := filepath.Join(dir, "git-state.json")
	write(state, fmt.Sprintf(`{"format": %q, "repositories": [{"path": %q}], "trees": {}, "commits": {}}`,
		"se-git-door-state/1", filepath.ToSlash(root)))
	release := filepath.Join(dir, "release")
	t.Cleanup(func() {
		_ = os.WriteFile(release, nil, 0o600)
		if _, err := host.AskStop(root); err != nil {
			t.Errorf("the case's stop: %v", err)
		}
	})

	cmd := exec.Command(se, "mcp", "--root", root, "--grace", "1s")
	cmd.Env = append(os.Environ(), cli.HoldEnv+"="+release, "SE_GIT_DOOR=fake:"+state)
	cmd.Stderr = os.Stderr
	client := sdk.NewClient(&sdk.Implementation{Name: "contract", Version: "0"}, nil)
	ctx, cancel := context.WithTimeout(context.Background(), time.Minute)
	defer cancel()
	began := time.Now()
	session, err := client.Connect(ctx, &sdk.CommandTransport{Command: cmd}, &sdk.ClientSessionOptions{ProtocolVersion: asks})
	if err != nil {
		t.Fatal(err)
	}
	answered := time.Since(began)
	result := session.InitializeResult()
	if result.ProtocolVersion != wants || result.ServerInfo == nil || result.ServerInfo.Name != "se" {
		t.Fatalf("the handshake answers the protocol %q and the server %+v, and wants %s and se", result.ProtocolVersion, result.ServerInfo, wants)
	}
	listed, err := session.ListTools(ctx, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Logf("protocol %s: the handshake answered %v after the spawn of se mcp, tools/list %v after it, the core's start held",
		wants, answered, time.Since(began)-answered)
	var names []string
	for _, tool := range listed.Tools {
		names = append(names, tool.Name)
		if !tool.Annotations.ReadOnlyHint || tool.Annotations.DestructiveHint == nil || *tool.Annotations.DestructiveHint {
			t.Errorf("tool %s carries %+v, and wants read-only and not destructive", tool.Name, tool.Annotations)
		}
	}
	if got := strings.Join(names, " "); got != "desk status" {
		t.Fatalf("tools/list answers %q, and wants desk and status", got)
	}
	// The door's supervisor starts the core beside the handshake, so its
	// claim can land after the first answers: the check waits for the claim
	// or a standing file, either a fact of a start begun, and then asks.
	begun := func() bool {
		for _, path := range []string{host.ClaimPath(root), host.StandingPath(root)} {
			if _, err := os.Stat(path); err == nil {
				return true
			}
		}
		return false
	}
	st, err := heldStart(begun, func() (host.Status, error) { return host.AskStatus(host.Wall{}, root) }, 10*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if st.State != host.StateStarting {
		t.Fatalf("while the start is held the core reads %q, and wants starting: the door answered before the core stood", st.State)
	}

	write(release, "")
	// running asks the status tool until it answers a core running that is
	// not the one of pid not, within the span given, and answers its pid and
	// how the door came to it.
	running := func(not int, within time.Duration) (int, string) {
		t.Helper()
		for end := time.Now().Add(within); time.Now().Before(end); {
			r, err := session.CallTool(ctx, &sdk.CallToolParams{Name: "status", Arguments: map[string]any{}})
			if err != nil {
				t.Fatal(err)
			}
			data, _ := json.Marshal(r.StructuredContent)
			var got struct {
				State  string      `json:"state"`
				Health host.Health `json:"health"`
				Core   string      `json:"core"`
			}
			_ = json.Unmarshal(data, &got)
			if got.State == string(host.StateRunning) && got.Health.Pid != not {
				if len(got.Health.Sessions) != 1 || !strings.HasPrefix(got.Health.Sessions[0], "mcp-") {
					t.Fatalf("the running core's sessions are %v, and want the door's one", got.Health.Sessions)
				}
				return got.Health.Pid, got.Core
			}
		}
		t.Fatalf("status never answers a new core running within %v", within)
		return 0, ""
	}
	pid, how := running(0, time.Minute)
	if how != mcp.Started {
		t.Fatalf("the door came to its first core %q, and wants %q", how, mcp.Started)
	}

	// The core stopped with se stop is started again by the next call, well
	// before the door's renewal, Renew away. The stopped core is the door's
	// child, which reaps it, so se stop returns once the core has ended.
	stop := exec.Command(se, "stop", "--root", root)
	stopped := time.Now()
	if out, err := stop.CombinedOutput(); err != nil {
		t.Fatalf("se stop: %v\n%s", err, out)
	}
	if took := time.Since(stopped); took > 5*time.Second {
		t.Fatalf("se stop returns %v after it was asked, and wants it at once", took)
	}
	if _, how := running(pid, mcp.Renew/2); how != mcp.StartedAgain {
		t.Fatalf("the door came to the core after se stop %q, and wants %q", how, mcp.StartedAgain)
	}
	t.Logf("a call after se stop answered a new core running %v after the stop", time.Since(stopped))

	if err := session.Close(); err != nil {
		t.Fatalf("the client's hang-up: %v", err)
	}
	for end := time.Now().Add(time.Minute); ; {
		st, err := host.AskStatus(host.Wall{}, root)
		if err == nil && st.State == host.StateStopped {
			break
		}
		if time.Now().After(end) {
			t.Fatalf("the core reads %q a minute after the session ended, and wants not running", st.State)
		}
		time.Sleep(50 * time.Millisecond)
	}
}

// heldStart waits until begun answers that the core's start has begun (its
// claim or its standing file is written), within the span given, and then
// answers the status ask reads. It fails naming what it waited for where the
// start never begins, and it never waits past the first fact, so a core that
// stood before the check reads running there.
func heldStart(begun func() bool, ask func() (host.Status, error), within time.Duration) (host.Status, error) {
	for end := time.Now().Add(within); !begun(); time.Sleep(time.Millisecond) {
		if time.Now().After(end) {
			return host.Status{}, fmt.Errorf("the core's start wrote neither its claim nor its standing file within %v of the door's answers", within)
		}
	}
	return ask()
}

// The wait before the held start's check: it answers the status once the
// start has begun, a running core among them, so a door that answers only
// after the core stood still fails the check; a start that never begins fails
// the wait, naming the claim.
func TestHeldStartWaitsForTheStartAndHidesNoRunningCore(t *testing.T) {
	after := func(n int) func() bool {
		calls := 0
		return func() bool { calls++; return calls > n }
	}
	for _, state := range []host.State{host.StateStarting, host.StateRunning} {
		asked := 0
		st, err := heldStart(after(3), func() (host.Status, error) { asked++; return host.Status{State: state}, nil }, time.Minute)
		if err != nil || st.State != state || asked != 1 {
			t.Errorf("a start begun on the fourth look reads %q (%v), asked %d times, and wants %q, asked once", st.State, err, asked, state)
		}
	}
	_, err := heldStart(func() bool { return false }, func() (host.Status, error) {
		t.Error("a start that never begins is asked its status")
		return host.Status{}, nil
	}, 20*time.Millisecond)
	if err == nil || !strings.Contains(err.Error(), "claim") {
		t.Errorf("a start that never begins fails the wait with %v, and wants it to name the claim", err)
	}
}
