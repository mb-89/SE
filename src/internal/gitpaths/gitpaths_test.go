package gitpaths_test

import (
	"os"
	"os/exec"
	"slices"
	"testing"

	"github.com/mb-89/SE/src/internal/gitenv"
	"github.com/mb-89/SE/src/internal/gitpaths"
	"github.com/mb-89/SE/src/internal/io/proc"
)

func TestMain(m *testing.M) {
	gitenv.Clear()
	os.Exit(m.Run())
}

// A merge that conflicts leaves its path in git's index once per stage; the
// list holds it once (#504).
func TestAConflictedPathIsListedOnce(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	git := func(args ...string) {
		t.Helper()
		c := exec.Command("git", append([]string{"-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false"}, args...)...)
		c.Dir = dir
		if out, err := c.CombinedOutput(); err != nil && args[0] != "merge" {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
	}
	write := func(name, text string) {
		t.Helper()
		if err := os.WriteFile(dir+"/"+name, []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	git("init", "-q")
	write("f.md", "a\n")
	write("g.md", "g\n")
	git("add", ".")
	git("commit", "-qm", "a")
	git("checkout", "-qb", "side")
	write("f.md", "b\n")
	git("commit", "-qam", "b")
	git("checkout", "-q", "main")
	write("f.md", "c\n")
	git("commit", "-qam", "c")
	git("merge", "side")
	write("new.md", "n\n")

	got, err := gitpaths.Tracked(proc.Real(), dir, false)
	if err != nil || !slices.Equal(got, []string{"f.md", "g.md"}) {
		t.Fatalf("%q %v", got, err)
	}
	got, err = gitpaths.Tracked(proc.Real(), dir, true)
	slices.Sort(got)
	if err != nil || !slices.Equal(got, []string{"f.md", "g.md", "new.md"}) {
		t.Fatalf("with others: %q %v", got, err)
	}
}
