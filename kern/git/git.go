// Package git is kern's one door to git: every git command kern and SE's Go
// components run goes through Run, so git is reached in one place (SE's rule
// book des-004). Its fake, gitfake, is held to the same contract cases as
// real git (contract_test.go, the counterpart of SE's tests/test_git_door.py);
// every other test uses the fake (Use), and a test binary that has chosen no
// backend is refused real git, naming the command, so no test reaches it by
// accident.
package git

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"sync"
	"testing"
)

// Command is one git command: its arguments after `git`, the folder it runs
// in (empty: the process's) and the variables laid over the environment, each
// NAME=value.
type Command struct {
	Dir  string
	Args []string
	Env  []string
}

// String names the command as an error names it.
func (c Command) String() string { return "git " + strings.Join(c.Args, " ") }

// Backend runs one git command and answers its standard output; a command
// git refuses answers an *Error.
type Backend interface {
	Run(ctx context.Context, c Command) (string, error)
}

// Error is a git command that exited non-zero, or that could not start.
type Error struct {
	Command Command
	Code    int // the exit code; -1 where git did not run
	Stderr  string
	Err     error
}

func (e *Error) Error() string {
	where := ""
	if e.Command.Dir != "" {
		where = " in " + e.Command.Dir
	}
	return fmt.Sprintf("%s%s: %v: %s", e.Command, where, e.Err, strings.TrimSpace(e.Stderr))
}

func (e *Error) Unwrap() error { return e.Err }

// Real is the git on PATH. Env is laid over the process's environment for
// every command, before the command's own: NAME=value sets a variable, a
// bare NAME removes it, so a contract run isolates git from the machine's
// configuration.
type Real struct {
	Env []string
}

// Run runs c with the git on PATH.
func (r Real) Run(ctx context.Context, c Command) (string, error) {
	cmd := exec.CommandContext(ctx, "git", c.Args...)
	cmd.Dir = c.Dir
	if len(r.Env) > 0 || len(c.Env) > 0 {
		cmd.Env = environment(os.Environ(), append(append([]string{}, r.Env...), c.Env...))
	}
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if err != nil {
		code := -1
		if exit, ok := err.(*exec.ExitError); ok {
			code = exit.ExitCode()
		}
		return string(out), &Error{Command: c, Code: code, Stderr: stderr.String(), Err: err}
	}
	return string(out), nil
}

// environment lays over onto base: NAME=value sets, a bare NAME removes.
func environment(base, over []string) []string {
	drop := map[string]bool{}
	for _, entry := range over {
		name, _, _ := strings.Cut(entry, "=")
		drop[name] = true
	}
	var env []string
	for _, entry := range base {
		if name, _, _ := strings.Cut(entry, "="); !drop[name] {
			env = append(env, entry)
		}
	}
	for _, entry := range over {
		if strings.Contains(entry, "=") {
			env = append(env, entry)
		}
	}
	return env
}

// refused is a test binary's backend until it chooses one with Use.
type refused struct{}

func (refused) Run(_ context.Context, c Command) (string, error) {
	return "", &Error{Command: c, Code: -1, Err: fmt.Errorf("refused"),
		Stderr: "a test reaches real git through kern's git door without choosing a backend; " +
			"install the fake (git.Use(gitfake.New()), in TestMain) or, in the contract suite only, git.Real"}
}

var (
	mu      sync.RWMutex
	current Backend
)

// backend answers the backend Run uses: the one Use installed, else real git,
// except in a test binary, which is refused it.
func backend() Backend {
	mu.RLock()
	defer mu.RUnlock()
	switch {
	case current != nil:
		return current
	case testing.Testing():
		return refused{}
	}
	return Real{}
}

// Use makes b the backend of every Run until the answered restore is called;
// a test installs the fake with it, once for its package (TestMain).
func Use(b Backend) (restore func()) {
	mu.Lock()
	before := current
	current = b
	mu.Unlock()
	return func() {
		mu.Lock()
		current = before
		mu.Unlock()
	}
}

// Run runs git with args in dir and answers its standard output.
func Run(ctx context.Context, dir string, args ...string) (string, error) {
	return backend().Run(ctx, Command{Dir: dir, Args: args})
}

// RunEnv is Run with variables laid over the environment, each NAME=value.
func RunEnv(ctx context.Context, dir string, env []string, args ...string) (string, error) {
	return backend().Run(ctx, Command{Dir: dir, Args: args, Env: env})
}
