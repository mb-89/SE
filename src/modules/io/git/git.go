// Package git is the I/O module for git: the one place SE runs git on a
// repository. Code that reads or changes a checkout takes a Git as an
// argument; the se binary hands it Real, a test hands it a Fake.
//
// Every git it runs finds its repository from the folder it runs in alone. A
// pre-push hook runs in git's environment, and from a worktree that holds
// GIT_DIR: a git run in another folder would act on the repository being
// pushed instead, so the module drops git's repository variables, Vars, from
// what each run inherits.
package git

import (
	"bytes"
	"fmt"
	"io"
	"slices"
	"strings"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/modules/io/env"
	"github.com/mb-89/SE/src/modules/io/proc"
)

// Git is what SE asks of git.
type Git interface {
	// Run runs git with c's words to its end. One that exits other than 0
	// fails with a *proc.ExitError; a machine without git with proc.ErrNotFound.
	Run(c Cmd) error
}

// Cmd is one run of git.
type Cmd struct {
	// Args are the words after git.
	Args []string
	// Dir is the folder it runs in, which names the repository; empty, the caller's.
	Dir string
	// Env is its environment, Vars dropped; nil, the caller's.
	Env []string
	// Stdout and Stderr take what it writes; nil, it goes nowhere.
	Stdout, Stderr io.Writer
}

// String is the command line, as an error names it.
func (c Cmd) String() string { return strings.Join(append([]string{"git"}, c.Args...), " ") }

// Module is git on the index: an I/O module.
var Module = index.Declare("io/git", "The git repositories SE reads and changes, each named by its folder.", index.IO())

func init() { index.Register(Module) }

// Vars are git's repository variables: each points git at a repository other
// than the one its working folder is in.
var Vars = []string{
	"GIT_DIR",
	"GIT_WORK_TREE",
	"GIT_INDEX_FILE",
	"GIT_PREFIX",
	"GIT_COMMON_DIR",
	"GIT_OBJECT_DIRECTORY",
	"GIT_ALTERNATE_OBJECT_DIRECTORIES",
}

// Isolated is env without Vars.
func Isolated(env []string) []string {
	return slices.DeleteFunc(slices.Clone(env), func(kv string) bool {
		k, _, _ := strings.Cut(kv, "=")
		return slices.Contains(Vars, k)
	})
}

// Clear unsets Vars in e, so every git a process runs past this module, and
// every process those start, finds its repository from its working folder. A
// package whose tests run git so calls it in TestMain on env.Real.
func Clear(e env.Env) error {
	for _, v := range Vars {
		if err := e.Unsetenv(v); err != nil {
			return err
		}
	}
	return nil
}

// Real answers git as the program on p, each run inheriting e's variables
// but Vars.
func Real(p proc.Procs, e env.Env) Git { return program{p, e} }

type program struct {
	p proc.Procs
	e env.Env
}

func (g program) Run(c Cmd) error {
	vars := c.Env
	if vars == nil {
		vars = g.e.Environ()
	}
	return g.p.Run(proc.Cmd{Name: "git", Args: c.Args, Dir: c.Dir, Env: Isolated(vars), Stdout: c.Stdout, Stderr: c.Stderr})
}

// Output runs git with args in dir and answers what it wrote to stdout,
// trimmed. A failure names the command and what it wrote to stderr.
func Output(g Git, dir string, args ...string) (string, error) {
	var out, stderr bytes.Buffer
	c := Cmd{Args: args, Dir: dir, Stdout: &out, Stderr: &stderr}
	if err := g.Run(c); err != nil {
		return "", fmt.Errorf("%s: %w: %s", c, err, strings.TrimSpace(stderr.String()))
	}
	return strings.TrimSpace(out.String()), nil
}

// Combined runs git with args in dir and answers what it wrote to stdout and
// stderr together, also when it fails.
func Combined(g Git, dir string, args ...string) ([]byte, error) {
	var out bytes.Buffer
	err := g.Run(Cmd{Args: args, Dir: dir, Stdout: &out, Stderr: &out})
	return out.Bytes(), err
}
