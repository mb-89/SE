package origin_test

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/mb-89/kern/git"
	"github.com/mb-89/kern/git/gitfake"
	"github.com/mb-89/se/components/origin"
)

// Every test reaches git through kern's git door, on its fake.
func TestMain(m *testing.M) {
	git.Use(gitfake.New())
	os.Exit(m.Run())
}

// Read answers origin's branches with the committer time of each tip, and
// leaves out origin's HEAD.
func TestReadAnswersOriginsBranches(t *testing.T) {
	dir := t.TempDir()
	run := func(args ...string) {
		t.Helper()
		env := []string{"GIT_COMMITTER_DATE=2026-11-13T09:00:00Z", "GIT_AUTHOR_DATE=2026-11-13T09:00:00Z",
			"GIT_AUTHOR_NAME=alice", "GIT_AUTHOR_EMAIL=alice@example.com", "GIT_COMMITTER_NAME=alice", "GIT_COMMITTER_EMAIL=alice@example.com"}
		if _, err := git.RunEnv(context.Background(), dir, env, args...); err != nil {
			t.Fatal(err)
		}
	}
	run("init", "-q")
	run("commit", "-q", "--allow-empty", "-m", "one")
	run("update-ref", "refs/remotes/origin/feat/x", "HEAD")
	run("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/feat/x")
	got, err := origin.Read(dir)
	if err != nil {
		t.Fatal(err)
	}
	want := time.Date(2026, 11, 13, 9, 0, 0, 0, time.UTC)
	if len(got) != 1 || !got["feat/x"].Equal(want) {
		t.Fatalf("origin's branches are %v, and want feat/x at 09:00 alone", got)
	}
}
