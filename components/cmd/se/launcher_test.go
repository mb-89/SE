package main

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/kern/cli"
	sdk "github.com/modelcontextprotocol/go-sdk/mcp"
)

// The door in a project that keeps no wiring of its own, as a host starts it
// through SE's launcher (scripts/se_mcp.sh): the launcher hands it this SE as
// its home, so an empty folder is offered SE's tools, while the bare door
// there offers status alone. SE's own checkout keeps its own wiring.
func TestAnEmptyFolderWithSEInstalledListsSEsToolsThroughTheLauncher(t *testing.T) {
	bash, err := exec.LookPath("bash")
	if err != nil || runtime.GOOS == "windows" {
		t.Skip("the launcher runs in bash; its Windows twin is tested in tests/test_se_mcp.py")
	}
	seRoot, err := filepath.Abs(filepath.Join("..", "..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	if got := cli.Source(seRoot, t.TempDir()); got != seRoot {
		t.Fatalf("SE's own checkout is served the wiring of %s, and wants its own", got)
	}
	dir := t.TempDir()
	se := filepath.Join(dir, "se")
	if out, err := exec.Command("go", "build", "-o", se, ".").CombinedOutput(); err != nil {
		t.Fatalf("go build of cmd/se: %v\n%s", err, out)
	}
	project := t.TempDir() // no .git: the door starts no core, and its tool list needs none
	list := func(cmd *exec.Cmd) string {
		t.Helper()
		cmd.Env = append(os.Environ(), "SE_MCP_BIN="+se, "HOME="+t.TempDir())
		ctx, cancel := context.WithTimeout(context.Background(), time.Minute)
		defer cancel()
		session, err := sdk.NewClient(&sdk.Implementation{Name: "host", Version: "0"}, nil).Connect(ctx, &sdk.CommandTransport{Command: cmd}, nil)
		if err != nil {
			t.Fatal(err)
		}
		defer session.Close()
		listed, err := session.ListTools(ctx, nil)
		if err != nil {
			t.Fatal(err)
		}
		var names []string
		for _, tool := range listed.Tools {
			names = append(names, tool.Name)
		}
		return strings.Join(names, " ")
	}
	launched := list(exec.Command(bash, filepath.Join(seRoot, "scripts", "se_mcp.sh"), "--root", project))
	if launched != "greeting integration overhaul status tickets" {
		t.Fatalf("through the launcher an empty folder is offered %q, and wants SE's tools", launched)
	}
	if bare := list(exec.Command(se, "mcp", "--root", project)); bare != "status" {
		t.Fatalf("the bare door in an empty folder offers %q, and wants status alone", bare)
	}
}
