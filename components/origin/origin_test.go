package origin_test

import (
	"os/exec"
	"testing"
	"time"

	"github.com/mb-89/se/components/origin"
)

// Read answers origin's branches with the committer time of each tip, and
// leaves out origin's HEAD.
func TestReadAnswersOriginsBranches(t *testing.T) {
	dir := t.TempDir()
	git := func(args ...string) {
		t.Helper()
		cmd := exec.Command("git", append([]string{"-C", dir, "-c", "maintenance.auto=false", "-c", "gc.auto=0"}, args...)...)
		cmd.Env = append(cmd.Environ(), "GIT_COMMITTER_DATE=2026-11-13T09:00:00Z", "GIT_AUTHOR_DATE=2026-11-13T09:00:00Z",
			"GIT_AUTHOR_NAME=alice", "GIT_AUTHOR_EMAIL=alice@example.com", "GIT_COMMITTER_NAME=alice", "GIT_COMMITTER_EMAIL=alice@example.com")
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
	}
	git("init", "-q")
	git("commit", "-q", "--allow-empty", "-m", "one")
	git("update-ref", "refs/remotes/origin/feat/x", "HEAD")
	git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/feat/x")
	got, err := origin.Read(dir)
	if err != nil {
		t.Fatal(err)
	}
	want := time.Date(2026, 11, 13, 9, 0, 0, 0, time.UTC)
	if len(got) != 1 || !got["feat/x"].Equal(want) {
		t.Fatalf("origin's branches are %v, and want feat/x at 09:00 alone", got)
	}
}
