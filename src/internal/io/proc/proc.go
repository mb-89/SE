// Package proc is the I/O module for programs: the one place SE starts git,
// go, check.sh, the se it hands over to, and the detached daemon. Code that
// runs a program takes a Procs as an argument; the se binary hands it Real, a
// test hands it a Fake with the programs its case needs installed.
//
// gh is not run through here: GitHub is its own module (#63).
package proc

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"strings"
)

// Cmd is one run of a program.
type Cmd struct {
	// Name is the program: a name looked up on the PATH, or a path.
	Name string
	// Args are the words after the program's name.
	Args []string
	// Dir is the folder it runs in; empty, the caller's.
	Dir string
	// Env is its whole environment; nil, the caller's.
	Env []string
	// Stdin is what it reads; nil, nothing.
	Stdin io.Reader
	// Stdout and Stderr take what it writes; nil, it goes nowhere.
	Stdout, Stderr io.Writer
	// Detached starts it in a session of its own, to outlive se: the daemon.
	Detached bool
}

// String is the command line, as an error names it.
func (c Cmd) String() string { return strings.Join(append([]string{c.Name}, c.Args...), " ") }

// Procs is what SE asks of programs.
type Procs interface {
	// Run runs c to its end. A program that is not there fails with
	// ErrNotFound; one that exits other than 0 with an *ExitError.
	Run(c Cmd) error
	// Start starts c and returns at once; the Running's Wait answers its end
	// as Run would.
	Start(c Cmd) (Running, error)
}

// Running is a program Start started.
type Running interface {
	// Wait returns once the program has ended, and answers as Run would.
	Wait() error
}

// ErrNotFound is the error of a program that is not there.
var ErrNotFound = errors.New("no such program")

// ExitError is the end of a program that exited other than 0.
type ExitError struct{ Code int }

func (e *ExitError) Error() string { return fmt.Sprintf("exit status %d", e.Code) }

// ExitCode answers the code a program's end err says it exited with: 0 for
// nil, the code for an *ExitError, and ok false for anything else, such as a
// program that never ran.
func ExitCode(err error) (code int, ok bool) {
	var exit *ExitError
	switch {
	case err == nil:
		return 0, true
	case errors.As(err, &exit):
		return exit.Code, true
	}
	return 0, false
}

// Output runs c and answers what it wrote to stdout, trimmed. A failure names
// the command and what it wrote to stderr.
func Output(p Procs, c Cmd) (string, error) {
	var out, stderr bytes.Buffer
	c.Stdout, c.Stderr = &out, &stderr
	if err := p.Run(c); err != nil {
		return "", fmt.Errorf("%s: %w: %s", c, err, strings.TrimSpace(stderr.String()))
	}
	return strings.TrimSpace(out.String()), nil
}

// Combined runs c and answers what it wrote to stdout and stderr together,
// also when it fails.
func Combined(p Procs, c Cmd) ([]byte, error) {
	var out bytes.Buffer
	c.Stdout, c.Stderr = &out, &out
	err := p.Run(c)
	return out.Bytes(), err
}
