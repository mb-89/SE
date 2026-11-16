package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mb-89/kern/cli"
	"github.com/mb-89/kern/index"
	"github.com/mb-89/kern/mcp"
	sdk "github.com/modelcontextprotocol/go-sdk/mcp"
)

var golden = flag.Bool("golden", false, "rewrite testdata/tools.json from SE's live tool list")

// surfaceBudget is the most SE's door may serve every turn: tools, bytes of
// one description, bytes of the whole list (mcp.Budget). A number unset, 0,
// holds nothing: unset, TestTheToolListKeepsItsBudget only reports.
var surfaceBudget = mcp.Budget{}

// toolsFile is SE's tool list as `se mcp --tools` prints it for SE's own
// tracked wiring.
var toolsFile = filepath.Join("testdata", "tools.json")

// rewrite is the command that rewrites toolsFile, run in components/.
const rewrite = "go test ./cmd/se -run TestTheCommittedToolListIsTheLiveOne -golden"

// liveTools is what `se mcp --tools --root <SE's checkout>` prints, in
// process, twice: the two runs must be byte for byte the same. A checkout
// with an ad hoc overlay (.se/wiring.toml) serves more than SE's tracked
// wiring, so the test skips there.
func liveTools(t *testing.T) []byte {
	t.Helper()
	root, err := filepath.Abs(filepath.Join("..", "..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(root, ".se", index.WiringFile)); err == nil {
		t.Skipf("%s carries an ad hoc overlay, .se/%s: its door serves more than SE's tracked wiring", root, index.WiringFile)
	}
	cli.Greeting = Greeting
	var runs [][]byte
	for range 2 {
		var out, errs bytes.Buffer
		if code := cli.Run("se", []string{"mcp", "--tools", "--root", root}, &out, &errs); code != 0 || errs.Len() > 0 {
			t.Fatalf("se mcp --tools exits %d and says %q, and wants 0 and nothing", code, errs.String())
		}
		runs = append(runs, out.Bytes())
	}
	if !bytes.Equal(runs[0], runs[1]) {
		t.Fatalf("two runs of se mcp --tools differ:\n%s\n%s", runs[0], runs[1])
	}
	return runs[0]
}

// The committed testdata/tools.json is the tool list SE's door serves for
// its tracked wiring, the whole file: a command's mcp line, a usage or a
// help that changes without it fails here, naming the command that rewrites
// it. It is also the input `host_size.py report --tools` measures.
func TestTheCommittedToolListIsTheLiveOne(t *testing.T) {
	got := liveTools(t)
	if *golden {
		if err := os.MkdirAll(filepath.Dir(toolsFile), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(toolsFile, got, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	want, err := os.ReadFile(toolsFile)
	if err != nil {
		t.Fatalf("%v: write it with %s", err, rewrite)
	}
	if string(got) != strings.ReplaceAll(string(want), "\r\n", "\n") {
		t.Fatalf("SE's door serves another tool list than %s holds: where the change is meant, rewrite it in components/ with\n\t%s\nand commit it. The live list:\n%s",
			filepath.ToSlash(toolsFile), rewrite, got)
	}
}

// SE's tool list measured (mcp.Measure) against surfaceBudget: the test logs
// the table and each tool's description beside the 2,048 characters at
// which a host is reported to cut one, and fails only on a number set.
func TestTheToolListKeepsItsBudget(t *testing.T) {
	var list struct {
		Tools []*sdk.Tool `json:"tools"`
	}
	if err := json.Unmarshal(liveTools(t), &list); err != nil {
		t.Fatal(err)
	}
	s, err := mcp.Measure(list.Tools)
	if err != nil {
		t.Fatal(err)
	}
	t.Logf("SE's tool list, in served order:\n%s", s.Table())
	const cut = 2048
	for _, tool := range s.Tools {
		if tool.Runes > cut {
			t.Logf("tool %s's description is %d characters, over the %d at which a host is reported to cut", tool.Name, tool.Runes, cut)
		}
	}
	if surfaceBudget == (mcp.Budget{}) {
		t.Logf("no budget set (surfaceBudget): reported only")
	}
	for _, over := range s.Over(surfaceBudget) {
		t.Errorf("SE's tool list is over its budget (surfaceBudget): %s", over)
	}
}
