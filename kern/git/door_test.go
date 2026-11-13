package git_test

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/mb-89/kern/git"
	"github.com/mb-89/kern/git/gitfake"
)

// A test binary that chose no backend is refused real git, naming the
// command and the remedy; Use installs a backend until its restore.
func TestATestIsRefusedRealGitUntilItChoosesABackend(t *testing.T) {
	_, err := git.Run(context.Background(), t.TempDir(), "status")
	var refused *git.Error
	if !errors.As(err, &refused) || !strings.Contains(err.Error(), "git status") ||
		!strings.Contains(refused.Stderr, "git.Use(gitfake.New())") {
		t.Fatalf("real git in a test answers %v", err)
	}
	fake := gitfake.New()
	restore := git.Use(fake)
	dir := t.TempDir()
	if _, err := git.Run(context.Background(), dir, "init", "-q"); err != nil {
		t.Fatal(err)
	}
	if _, err := git.RunEnv(context.Background(), dir, []string{"GIT_AUTHOR_NAME=alice"}, "rev-parse", "--show-prefix"); err != nil {
		t.Fatal(err)
	}
	restore()
	if calls := fake.Calls(); len(calls) != 2 || calls[0][0] != "init" || calls[1][0] != "rev-parse" {
		t.Fatalf("the fake ran %v", calls)
	}
	if _, err := git.Run(context.Background(), dir, "status"); !errors.As(err, &refused) {
		t.Fatalf("after restore, real git in a test answers %v", err)
	}
}

// A command the fake does not answer fails with git's usage code, naming
// itself, so a new caller extends the fake and the contract together.
func TestTheFakeRefusesACommandItDoesNotAnswer(t *testing.T) {
	_, err := gitfake.New().Run(context.Background(), git.Command{Dir: t.TempDir(), Args: []string{"-c", "a=b", "rebase"}})
	var refused *git.Error
	if !errors.As(err, &refused) || refused.Code != 129 || !strings.Contains(refused.Stderr, "no `rebase`") {
		t.Fatalf("the fake's rebase answers %v", err)
	}
}
