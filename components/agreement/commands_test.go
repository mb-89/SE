package agreement

import (
	"bytes"
	"encoding/json"
	"os/exec"
	"path/filepath"
	"reflect"
	"testing"

	"se/components/template"
)

// The rule dangling's command discovery: the Go template engine reads each script's subcommands
// from its source (template.CommandTree), the Python one from its argparse parser
// (scripts/references.py command_tree); for every script of SE's checkout both read the same tree.
func TestTheCommandTreesAgree(t *testing.T) {
	root, err := filepath.Abs(filepath.Join("..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(python(t), filepath.Join("testdata", "command_trees.py"), root)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if err != nil {
		t.Fatalf("the Python command trees failed: %v\n%s", err, stderr.String())
	}
	var want map[string]template.Tree
	if err := json.Unmarshal(out, &want); err != nil {
		t.Fatalf("the Python command trees answered no JSON: %v\n%s", err, out)
	}
	scripts, err := filepath.Glob(filepath.Join(root, "scripts", "*.py"))
	if err != nil || len(scripts) == 0 {
		t.Fatalf("no scripts under %s: %v", root, err)
	}
	trees := 0
	for _, script := range scripts {
		name := filepath.Base(script)
		got, wanted := template.CommandTree(script), want[name]
		if wanted == nil {
			wanted = template.Tree{}
		}
		if !reflect.DeepEqual(got, wanted) {
			t.Errorf("%s: Go reads the tree %v, Python's parser %v", name, got, wanted)
		}
		if len(wanted) > 0 {
			trees++
		}
	}
	if trees < 20 {
		t.Errorf("only %d scripts define subcommands; the reading lost its scripts", trees)
	}
}
