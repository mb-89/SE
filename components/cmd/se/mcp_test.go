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

	"github.com/mb-89/kern/cli"
	"github.com/mb-89/kern/host"
	"github.com/mb-89/kern/index"
	"github.com/mb-89/kern/mcp"
	sdk "github.com/modelcontextprotocol/go-sdk/mcp"
)

// SE's own catalog, its root wiring.toml and its components' declarations as
// the core reads them, passes the MCP door's catalog check, and makes a few
// coarse tools: status, the greeting with every part it reads, and one per
// command group that offers read-only commands.
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
	}
	if got := strings.Join(names, " "); got != "status greeting integration overhaul tickets" || len(tools) < 3 || len(tools) > 8 {
		t.Fatalf("SE's door offers the tools %q, and wants status, greeting, integration, overhaul and tickets", got)
	}
}

// The door's contract, the one test with a real MCP client (the Go SDK's)
// against the built `se mcp` and the real core it starts: initialize and
// tools/list answer while the core's start is held, status answers once it
// runs with the door's session holding a lease, and the core ends its grace
// after the client hangs up.
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
	session, err := client.Connect(ctx, &sdk.CommandTransport{Command: cmd}, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Logf("initialize answered %v after the spawn of se mcp, the core's start held", time.Since(began))
	if info := session.InitializeResult().ServerInfo; info.Name != "se" {
		t.Fatalf("initialize names the server %+v, and wants se", info)
	}
	listed, err := session.ListTools(ctx, nil)
	if err != nil {
		t.Fatal(err)
	}
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
	if st, _ := host.AskStatus(host.Wall{}, root); st.State != host.StateStarting {
		t.Fatalf("while the start is held the core reads %q, and wants starting: the door answered before the core stood", st.State)
	}

	write(release, "")
	var running bool
	for end := time.Now().Add(time.Minute); !running && time.Now().Before(end); {
		r, err := session.CallTool(ctx, &sdk.CallToolParams{Name: "status", Arguments: map[string]any{}})
		if err != nil {
			t.Fatal(err)
		}
		data, _ := json.Marshal(r.StructuredContent)
		var got struct {
			State  string      `json:"state"`
			Health host.Health `json:"health"`
		}
		_ = json.Unmarshal(data, &got)
		if got.State == string(host.StateRunning) {
			running = true
			if len(got.Health.Sessions) != 1 || !strings.HasPrefix(got.Health.Sessions[0], "mcp-") {
				t.Fatalf("the running core's sessions are %v, and want the door's one", got.Health.Sessions)
			}
		}
	}
	if !running {
		t.Fatal("status never answers running after the start's release")
	}

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
