package git_test

import (
	"errors"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/modules/io/git"
	"github.com/mb-89/SE/src/modules/io/proc"
)

// contract is the one suite every Git keeps, the fake as the real one. fresh
// answers git and the folder of a new repository for each case.
func contract(t *testing.T, fresh func(t *testing.T) (git.Git, string)) {
	t.Run("git runs in the repository its folder names", func(t *testing.T) {
		g, dir := fresh(t)
		if top, err := git.Output(g, dir, "rev-parse", "--show-toplevel"); err != nil || top != dir {
			t.Fatalf("top %q, %v; want %q", top, err, dir)
		}
	})
	t.Run("git's repository variables never reach it", func(t *testing.T) {
		g, dir := fresh(t)
		var out strings.Builder
		c := git.Cmd{Args: []string{"rev-parse", "--show-toplevel"}, Dir: dir, Stdout: &out, Env: []string{"GIT_DIR=" + dir + "/nowhere", "GIT_WORK_TREE=" + dir + "/nowhere"}}
		if err := g.Run(c); err != nil || strings.TrimSpace(out.String()) != dir {
			t.Fatalf("top %q, %v; want %q", out.String(), err, dir)
		}
	})
	t.Run("a failure says what git said", func(t *testing.T) {
		g, dir := fresh(t)
		_, err := git.Output(g, dir, "no-such-command")
		var exit *proc.ExitError
		if !errors.As(err, &exit) || !strings.Contains(err.Error(), "git no-such-command: ") || !strings.Contains(err.Error(), "'no-such-command' is not a git command") {
			t.Fatalf("%v", err)
		}
		if out, err := git.Combined(g, dir, "no-such-command"); err == nil || !strings.Contains(string(out), "is not a git command") {
			t.Fatalf("%q, %v", out, err)
		}
	})
}
