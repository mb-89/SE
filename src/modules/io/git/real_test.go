package git_test

import (
	"path/filepath"
	"testing"

	"github.com/mb-89/SE/src/modules/io/env"
	"github.com/mb-89/SE/src/modules/io/git"
	"github.com/mb-89/SE/src/modules/io/proc"
)

func TestTheRealGitKeepsTheContract(t *testing.T) {
	t.Parallel()
	contract(t, func(t *testing.T) (git.Git, string) {
		dir, err := filepath.EvalSymlinks(t.TempDir())
		if err != nil {
			t.Fatal(err)
		}
		g := git.Real(proc.Real(), env.Real())
		if out, err := git.Combined(g, dir, "init", "-q"); err != nil {
			t.Fatalf("git init: %v: %s", err, out)
		}
		return g, filepath.ToSlash(dir)
	})
}
