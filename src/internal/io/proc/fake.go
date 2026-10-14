package proc

import (
	"fmt"
	"io"
	"strings"
	"sync"
)

// Program is a program installed on a Fake: it does what the real one would
// with c and answers its exit code. Its Stdin, Stdout and Stderr are never nil.
type Program func(c Cmd) int

// Fake is a machine that holds only the programs a case installs on it. It
// runs them as the real machine would its own and records every run, in
// order; a program it does not hold is not found.
type Fake struct {
	mu       sync.Mutex
	programs map[string]Program
	ran      []Cmd
	self     string
}

// NewFake answers a fake machine with no programs on it.
func NewFake() *Fake { return &Fake{programs: map[string]Program{}} }

// Install puts p on the machine as name, replacing what was there.
func (f *Fake) Install(name string, p Program) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.programs[name] = p
}

// RunAs makes name the program running now, which Self answers: an installed
// one, or a path the case names.
func (f *Fake) RunAs(name string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.self = name
}

// Self answers the program RunAs named; on a machine where none was, it fails.
func (f *Fake) Self() (string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.self == "" {
		return "", fmt.Errorf("the fake machine runs no program as itself: %w", ErrNotFound)
	}
	return f.self, nil
}

// Ran answers every run asked of the machine, found or not, in order.
func (f *Fake) Ran() []Cmd {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]Cmd(nil), f.ran...)
}

// Lines answers each run as its command line, in order.
func (f *Fake) Lines() []string {
	var out []string
	for _, c := range f.Ran() {
		out = append(out, c.String())
	}
	return out
}

// Run runs the installed program to its end.
func (f *Fake) Run(c Cmd) error {
	r, err := f.Start(c)
	if err != nil {
		return err
	}
	return r.Wait()
}

// Start starts the installed program and returns at once.
func (f *Fake) Start(c Cmd) (Running, error) {
	f.mu.Lock()
	f.ran = append(f.ran, c)
	p, ok := f.programs[c.Name]
	f.mu.Unlock()
	if !ok {
		return nil, fmt.Errorf("%s: %w", c.Name, ErrNotFound)
	}
	if c.Stdin == nil {
		c.Stdin = strings.NewReader("")
	}
	if c.Stdout == nil {
		c.Stdout = io.Discard
	}
	if c.Stderr == nil {
		c.Stderr = io.Discard
	}
	r := &fakeRun{done: make(chan struct{})}
	go func() {
		defer close(r.done)
		if code := p(c); code != 0 {
			r.err = &ExitError{Code: code}
		}
	}()
	return r, nil
}

type fakeRun struct {
	done chan struct{}
	err  error
}

func (r *fakeRun) Wait() error {
	<-r.done
	return r.err
}
