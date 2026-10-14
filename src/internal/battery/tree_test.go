package battery_test

import (
	"fmt"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/battery"
	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// stamp is where the tests keep the battery's stamp.
const stamp = battery.Stamp

// worktree is a fake git's checkout at /w: what git status says of it but
// for the stamp, the entries its HEAD's tree lists, and the stamp HEAD holds
// ("" for none).
type worktree struct {
	dirty   string
	entries []string
	stamped string
}

func (w *worktree) git(c proc.Cmd) int {
	switch strings.Join(c.Args, " ") {
	case "status --porcelain -- . :(exclude)" + stamp:
		_, _ = fmt.Fprint(c.Stdout, w.dirty)
	case "ls-tree -r -z --full-tree HEAD":
		entries := w.entries
		if w.stamped != "" {
			entries = append(entries[:len(entries):len(entries)], "100644 blob 5555555555555555555555555555555555555555\t"+stamp)
		}
		for _, e := range entries {
			_, _ = fmt.Fprint(c.Stdout, e+"\x00")
		}
	case "ls-tree --name-only --full-tree HEAD -- " + stamp:
		if w.stamped != "" {
			fmt.Fprintln(c.Stdout, stamp)
		}
	case "show HEAD:" + stamp:
		fmt.Fprintln(c.Stdout, w.stamped)
	default:
		fmt.Fprintf(c.Stderr, "fatal: %s\n", c.Args)
		return 128
	}
	return 0
}

var (
	treeA = []string{"100644 blob 4b825dc642cb6eb9a060e54bf8d69288fbee4904\tgo.mod"}
	treeB = []string{"100644 blob aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\tgo.mod"}
)

// fakeGit is a fake machine whose git answers for w.
func fakeGit(w *worktree) *proc.Fake {
	m := proc.NewFake()
	m.Install("git", w.git)
	return m
}

func TestTheBatteryStampsTheCleanTreeItPassed(t *testing.T) {
	t.Parallel()
	w := &worktree{entries: treeA}
	m := fakeGit(w)
	d := disk.NewFake()
	started, err := battery.Tree(m, "/w", stamp)
	if err != nil || len(started) != 64 {
		t.Fatalf("%q %v", started, err)
	}
	if said, err := battery.Pass(d, m, "/w", stamp, started); err != nil || !strings.Contains(said, started) {
		t.Fatalf("%q %v", said, err)
	}
	if got, err := d.ReadFile("/w/" + stamp); err != nil || string(got) != started+"\n" {
		t.Fatalf("%q %v", got, err)
	}
	// Committed, the stamp leaves the hash as it was: it is left out of it.
	w.stamped = started
	if got, err := battery.Tree(m, "/w", stamp); err != nil || got != started {
		t.Fatalf("%q %v, want %q", got, err, started)
	}
	w.entries = treeB
	if got, err := battery.Tree(m, "/w", stamp); err != nil || got == started {
		t.Fatalf("another tree hashes as %q %v", got, err)
	}
}

func TestTheBatteryStampsNoTreeItDidNotRunOverWhole(t *testing.T) {
	t.Parallel()
	w := &worktree{entries: treeA, dirty: " M x\n"}
	m := fakeGit(w)
	d := disk.NewFake()
	// A dirty worktree is no tree.
	if started, err := battery.Tree(m, "/w", stamp); err != nil || started != "" {
		t.Fatalf("%q %v", started, err)
	}
	if said, err := battery.Pass(d, m, "/w", stamp, ""); err != nil || !strings.Contains(said, "writes no stamp") {
		t.Fatalf("%q %v", said, err)
	}
	// A commit made while it ran is not what it checked.
	w.dirty = ""
	started, _ := battery.Tree(m, "/w", stamp)
	w.entries = treeB
	if said, err := battery.Pass(d, m, "/w", stamp, started); err != nil || !strings.Contains(said, "moved from tree "+started) {
		t.Fatalf("%q %v", said, err)
	}
	// So is a change left uncommitted at the end.
	w.dirty, w.entries = "?? y\n", treeA
	if said, err := battery.Pass(d, m, "/w", stamp, started); err != nil || !strings.Contains(said, "writes no stamp") {
		t.Fatalf("%q %v", said, err)
	}
	if _, err := d.ReadFile("/w/" + stamp); err == nil {
		t.Fatal("a stamp was written")
	}
}

func TestATreeIsTrustedOnlyWhereItsStampNamesIt(t *testing.T) {
	t.Parallel()
	w := &worktree{entries: treeA}
	m := fakeGit(w)
	if _, err := battery.Trusted(m, "/w", "HEAD", stamp); err == nil || !strings.Contains(err.Error(), "holds no stamp") {
		t.Fatalf("%v", err)
	}
	hash, _ := battery.Hash(m, "/w", "HEAD", stamp)
	w.stamped = hash
	if why, err := battery.Trusted(m, "/w", "HEAD", stamp); err != nil || !strings.Contains(why, hash) {
		t.Fatalf("%q %v", why, err)
	}
	// Main moved: the tree is not the one the stamp names.
	w.entries = treeB
	if _, err := battery.Trusted(m, "/w", "HEAD", stamp); err == nil || !strings.Contains(err.Error(), "changed since the battery passed") {
		t.Fatalf("%v", err)
	}
	// Two stamps a merge put together name no hash.
	w.stamped = hash + "\n" + hash
	if _, err := battery.Trusted(m, "/w", "HEAD", stamp); err == nil || !strings.Contains(err.Error(), "names no hash") {
		t.Fatalf("%v", err)
	}
}
