package git_test

import (
	"fmt"
	"slices"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/modules/io/env"
	"github.com/mb-89/SE/src/modules/io/git"
	"github.com/mb-89/SE/src/modules/io/proc"
)

// toplevel is a git that knows where each repository's top is, and nothing
// else: as the real one, it follows GIT_WORK_TREE where that is set.
func toplevel(c proc.Cmd) int {
	switch strings.Join(c.Args, " ") {
	case "rev-parse --show-toplevel":
		top := c.Dir
		for _, kv := range c.Env {
			if v, ok := strings.CutPrefix(kv, "GIT_WORK_TREE="); ok {
				top = v
			}
		}
		fmt.Fprintln(c.Stdout, top)
		return 0
	}
	fmt.Fprintf(c.Stderr, "git: '%s' is not a git command. See 'git --help'.\n", c.Args[0])
	return 1
}

func TestTheFakeGitKeepsTheContract(t *testing.T) {
	t.Parallel()
	contract(t, func(t *testing.T) (git.Git, string) { return git.NewFake(toplevel), "/repo" })
}

func TestTheFakeGitRecordsEachRun(t *testing.T) {
	t.Parallel()
	g := git.NewFake(toplevel)
	if _, err := git.Output(g, "/repo", "rev-parse", "--show-toplevel"); err != nil {
		t.Fatal(err)
	}
	if got := g.Machine.Lines(); !slices.Equal(got, []string{"git rev-parse --show-toplevel"}) {
		t.Fatalf("ran %q", got)
	}
}

func TestIsolatedDropsGitsRepositoryVariablesAlone(t *testing.T) {
	t.Parallel()
	got := git.Isolated([]string{"HOME=/h", "GIT_DIR=/d", "GIT_AUTHOR_NAME=a", "GIT_INDEX_FILE=/i"})
	if !slices.Equal(got, []string{"HOME=/h", "GIT_AUTHOR_NAME=a"}) {
		t.Fatalf("%q", got)
	}
}

func TestClearUnsetsGitsRepositoryVariables(t *testing.T) {
	t.Parallel()
	e := env.NewFake("HOME=/h", "GIT_DIR=/d", "GIT_WORK_TREE=/w")
	if err := git.Clear(e); err != nil {
		t.Fatal(err)
	}
	if got := e.Environ(); len(got) != 1 || got[0] != "HOME=/h" {
		t.Fatalf("%q", got)
	}
}
