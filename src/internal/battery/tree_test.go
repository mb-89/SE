package battery_test

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/battery"
	"github.com/mb-89/SE/src/internal/gitenv"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// TestMain keeps the git these tests run in their own temp repositories,
// away from the decoy the battery runs go test on.
func TestMain(m *testing.M) {
	gitenv.Clear()
	os.Exit(m.Run())
}

// gitAt runs git in dir and answers what it printed.
func gitAt(t *testing.T, dir string, args ...string) string {
	t.Helper()
	out, err := exec.Command("git", append([]string{"-C", dir, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"}, args...)...).CombinedOutput()
	if err != nil {
		t.Fatalf("git %v: %v %s", args, err, out)
	}
	return strings.TrimSpace(string(out))
}

// put writes text to name in dir.
func put(t *testing.T, dir, name, text string) {
	t.Helper()
	at := filepath.Join(dir, filepath.FromSlash(name))
	if err := os.MkdirAll(filepath.Dir(at), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(at, []byte(text), 0o644); err != nil {
		t.Fatal(err)
	}
}

// checkout is a repository with one commit of code and no record of a pass.
func checkout(t *testing.T) string {
	t.Helper()
	w := t.TempDir()
	gitAt(t, w, "init", "-q", "-b", "main")
	put(t, w, "src/a.go", "package a\n")
	put(t, w, "README.md", "r\n")
	gitAt(t, w, "add", "-A")
	gitAt(t, w, "commit", "-q", "-m", "start")
	return w
}

var git = proc.Real()

// The record of a pass names the tree without itself, so committing it
// changes nothing it names: where HEAD holds no record, that is HEAD's tree,
// and a folder holding the record alone is left out with it.
func TestTheBatteryRecordsTheTreeItPassedWithoutItself(t *testing.T) {
	t.Parallel()
	w := checkout(t)
	head := gitAt(t, w, "rev-parse", "HEAD^{tree}")
	started, err := battery.Tree(git, w)
	if err != nil || started != head {
		t.Fatalf("%q %v, want %s", started, err, head)
	}
	if said, err := battery.Pass(machine, git, w, started); err != nil || !strings.Contains(said, head) {
		t.Fatalf("%q %v", said, err)
	}
	file, err := battery.Passed()
	if err != nil {
		t.Fatal(err)
	}
	// The record left in the worktree is no change the battery refuses.
	if again, err := battery.Tree(git, w); err != nil || again != head {
		t.Fatalf("%q %v", again, err)
	}
	if got, ok, err := battery.Stage(git, w); err != nil || !ok || got != head {
		t.Fatalf("%q %v %v", got, ok, err)
	}
	if err := battery.Commit(git, w, head); err != nil {
		t.Fatal(err)
	}
	if got := gitAt(t, w, "show", "--format=%s", "--name-only", "HEAD"); got != "The battery passed tree "+head+"\n\n"+file {
		t.Fatalf("the commit is %q", got)
	}
	if tree, err := battery.TreeOf(git, w, "HEAD"); err != nil || tree != head {
		t.Fatalf("%q %v, want %s", tree, err, head)
	}
	if got, ok, err := battery.Recorded(git, w, "HEAD"); err != nil || !ok || got != head {
		t.Fatalf("%q %v %v", got, ok, err)
	}
	// Nothing left to commit, it commits nothing.
	if err := battery.Commit(git, w, head); err != nil || gitAt(t, w, "rev-list", "--count", "HEAD") != "2" {
		t.Fatalf("%v", err)
	}
}

func TestTheBatteryRecordsNoTreeItDidNotRunOverWhole(t *testing.T) {
	t.Parallel()
	w := checkout(t)
	head := gitAt(t, w, "rev-parse", "HEAD^{tree}")
	// A dirty worktree is no tree.
	put(t, w, "src/a.go", "package b\n")
	if started, err := battery.Tree(git, w); err != nil || started != "" {
		t.Fatalf("%q %v", started, err)
	}
	if said, err := battery.Pass(machine, git, w, ""); err != nil || !strings.Contains(said, "records no tree") {
		t.Fatalf("%q %v", said, err)
	}
	// A commit made while it ran is not what it checked.
	gitAt(t, w, "commit", "-q", "-am", "more")
	if said, err := battery.Pass(machine, git, w, head); err != nil || !strings.Contains(said, "moved from tree "+head) {
		t.Fatalf("%q %v", said, err)
	}
	// So is a change left uncommitted at the end.
	put(t, w, "y", "y\n")
	if said, err := battery.Pass(machine, git, w, head); err != nil || !strings.Contains(said, "records no tree") {
		t.Fatalf("%q %v", said, err)
	}
	if got, ok, err := battery.Stage(git, w); err != nil || ok {
		t.Fatalf("%q %v %v", got, ok, err)
	}
}

func TestARecordNamingNoTreeIsAnError(t *testing.T) {
	t.Parallel()
	w := checkout(t)
	file, err := battery.Passed()
	if err != nil {
		t.Fatal(err)
	}
	put(t, w, file, "not a tree\n")
	if _, ok, err := battery.Stage(git, w); err == nil || ok {
		t.Fatalf("%v %v", ok, err)
	}
}

// Before a merge the record goes back to HEAD's, and a merge that conflicts
// in the record alone is settled with the branch's own.
func TestTheRecordStopsNoMerge(t *testing.T) {
	t.Parallel()
	w := checkout(t)
	file, err := battery.Passed()
	if err != nil {
		t.Fatal(err)
	}
	// Reset takes away a record HEAD does not hold.
	put(t, w, file, "1111111111111111111111111111111111111111\n")
	if err := battery.Reset(git, w); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(w, file)); !os.IsNotExist(err) {
		t.Fatalf("the record is still there: %v", err)
	}
	put(t, w, file, "1111111111111111111111111111111111111111\n")
	gitAt(t, w, "add", "-A")
	gitAt(t, w, "commit", "-q", "-m", "a record")
	gitAt(t, w, "checkout", "-q", "-b", "other")
	put(t, w, file, "2222222222222222222222222222222222222222\n")
	gitAt(t, w, "commit", "-q", "-am", "its record")
	gitAt(t, w, "checkout", "-q", "main")
	put(t, w, file, "3333333333333333333333333333333333333333\n")
	gitAt(t, w, "commit", "-q", "-am", "main's record")
	// Reset puts back HEAD's.
	put(t, w, file, "4444444444444444444444444444444444444444\n")
	if err := battery.Reset(git, w); err != nil || gitAt(t, w, "status", "--porcelain") != "" {
		t.Fatalf("%v", err)
	}
	if _, err := exec.Command("git", "-C", w, "merge", "-q", "--no-edit", "other").CombinedOutput(); err == nil {
		t.Fatal("the records merged without a conflict")
	}
	if settled, err := battery.Resolve(git, w); err != nil || !settled {
		t.Fatalf("%v %v", settled, err)
	}
	if got, ok, err := battery.Recorded(git, w, ""); err != nil || !ok || got != "3333333333333333333333333333333333333333" {
		t.Fatalf("%q %v %v", got, ok, err)
	}
	gitAt(t, w, "commit", "-q", "--no-edit")
	// Another file in conflict is left to the box.
	gitAt(t, w, "checkout", "-q", "other")
	put(t, w, "README.md", "theirs\n")
	put(t, w, file, "5555555555555555555555555555555555555555\n")
	gitAt(t, w, "commit", "-q", "-am", "both")
	gitAt(t, w, "checkout", "-q", "main")
	put(t, w, "README.md", "ours\n")
	put(t, w, file, "6666666666666666666666666666666666666666\n")
	gitAt(t, w, "commit", "-q", "-am", "both")
	if _, err := exec.Command("git", "-C", w, "merge", "-q", "--no-edit", "other").CombinedOutput(); err == nil {
		t.Fatal("the merge did not conflict")
	}
	if settled, err := battery.Resolve(git, w); err != nil || settled {
		t.Fatalf("%v %v", settled, err)
	}
}
