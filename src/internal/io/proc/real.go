package proc

import (
	"errors"
	"io/fs"
	"os"
	"os/exec"
)

// Real runs the programs on this machine.
func Real() Procs { return machine{} }

type machine struct{}

func (machine) Run(c Cmd) error {
	r, err := machine{}.Start(c)
	if err != nil {
		return err
	}
	return r.Wait()
}

func (machine) Start(c Cmd) (Running, error) {
	cmd := exec.Command(c.Name, c.Args...)
	cmd.Dir, cmd.Env = c.Dir, c.Env
	cmd.Stdin, cmd.Stdout, cmd.Stderr = c.Stdin, c.Stdout, c.Stderr
	if c.Detached {
		cmd.SysProcAttr = detached()
	}
	if err := cmd.Start(); err != nil {
		var path *fs.PathError
		if errors.As(err, &path) && path.Path == cmd.Path && errors.Is(err, fs.ErrNotExist) {
			return nil, &notFound{c.Name, err}
		}
		return nil, ended(c, err)
	}
	return running{c, cmd}, nil
}

func (machine) Self() (string, error) { return os.Executable() }

type running struct {
	c   Cmd
	cmd *exec.Cmd
}

func (r running) Wait() error { return ended(r.c, r.cmd.Wait()) }

// ended says err in this module's words: ErrNotFound, an *ExitError, or as it was.
func ended(c Cmd, err error) error {
	var exit *exec.ExitError
	var lookup *exec.Error
	switch {
	case err == nil:
		return nil
	case errors.As(err, &lookup):
		return &notFound{c.Name, err}
	case errors.As(err, &exit):
		return &ExitError{Code: exit.ExitCode()}
	}
	return err
}

// notFound is ErrNotFound for one program, keeping what the system said.
type notFound struct {
	name string
	err  error
}

func (n *notFound) Error() string {
	return n.name + ": " + ErrNotFound.Error() + " (" + n.err.Error() + ")"
}
func (n *notFound) Is(target error) bool { return target == ErrNotFound }
func (n *notFound) Unwrap() error        { return n.err }
