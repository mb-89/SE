package battery_test

import (
	"fmt"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/battery"
	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// worktree is a fake git's checkout at /w: what git status says of it, and the tree its HEAD names.
type worktree struct{ dirty, tree string }

func (w *worktree) git(c proc.Cmd) int {
	switch strings.Join(c.Args, " ") {
	case "status --porcelain":
		_, _ = fmt.Fprint(c.Stdout, w.dirty)
	case "rev-parse HEAD^{tree}":
		fmt.Fprintln(c.Stdout, w.tree)
	default:
		fmt.Fprintf(c.Stderr, "fatal: %s\n", c.Args)
		return 128
	}
	return 0
}

const (
	treeA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
	treeB = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
)

func TestTheBatteryRecordsTheCleanTreeItPassed(t *testing.T) {
	t.Parallel()
	w := &worktree{tree: treeA}
	m := proc.NewFake()
	m.Install("git", w.git)
	d := disk.NewFake()
	started, err := battery.Tree(m, "/w")
	if err != nil || started != treeA {
		t.Fatalf("%q %v", started, err)
	}
	if said, err := battery.Pass(d, m, "/w", started); err != nil || !strings.Contains(said, treeA) {
		t.Fatalf("%q %v", said, err)
	}
	if got, ok, err := battery.Passed(d, "/w"); err != nil || !ok || got != treeA {
		t.Fatalf("%q %v %v", got, ok, err)
	}
}

func TestTheBatteryRecordsNoTreeItDidNotRunOverWhole(t *testing.T) {
	t.Parallel()
	w := &worktree{tree: treeA, dirty: " M x\n"}
	m := proc.NewFake()
	m.Install("git", w.git)
	d := disk.NewFake()
	// A dirty worktree is no tree.
	if started, err := battery.Tree(m, "/w"); err != nil || started != "" {
		t.Fatalf("%q %v", started, err)
	}
	if said, err := battery.Pass(d, m, "/w", ""); err != nil || !strings.Contains(said, "records no tree") {
		t.Fatalf("%q %v", said, err)
	}
	// A commit made while it ran is not what it checked.
	w.dirty, w.tree = "", treeB
	if said, err := battery.Pass(d, m, "/w", treeA); err != nil || !strings.Contains(said, "moved from tree "+treeA) {
		t.Fatalf("%q %v", said, err)
	}
	// So is a change left uncommitted at the end.
	w.dirty, w.tree = "?? y\n", treeA
	if said, err := battery.Pass(d, m, "/w", treeA); err != nil || !strings.Contains(said, "records no tree") {
		t.Fatalf("%q %v", said, err)
	}
	if got, ok, err := battery.Passed(d, "/w"); err != nil || ok {
		t.Fatalf("%q %v %v", got, ok, err)
	}
}

func TestATreeFileNamingNoTreeIsAnError(t *testing.T) {
	t.Parallel()
	d := disk.NewFake()
	if err := d.MkdirAll("/w/" + battery.Dir); err != nil {
		t.Fatal(err)
	}
	if err := d.WriteFile("/w/"+battery.Dir+"/"+battery.TreeFile, []byte("not a tree\n")); err != nil {
		t.Fatal(err)
	}
	if _, ok, err := battery.Passed(d, "/w"); err == nil || ok {
		t.Fatalf("%v %v", ok, err)
	}
}
