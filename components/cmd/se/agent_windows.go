package main

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"

	"golang.org/x/sys/windows"
)

// start runs the host at path with args on se's own stdin, stdout and
// stderr, ignoring Ctrl+C itself while it runs, and answers the host's exit
// code: Windows has no exec.
func start(path string, args []string, stderr io.Writer) int {
	cmd := exec.Command(path, args...)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	signal.Ignore(os.Interrupt)
	defer signal.Reset(os.Interrupt)
	if err := cmd.Run(); err != nil {
		if ee, ok := err.(*exec.ExitError); ok {
			return ee.ExitCode()
		}
		fmt.Fprintf(stderr, "se agent: cannot start %s: %v\n", path, err)
		return 1
	}
	return 0
}

// terminal reports whether f is a console, as its console mode says.
func terminal(f *os.File) bool {
	var mode uint32
	return windows.GetConsoleMode(windows.Handle(f.Fd()), &mode) == nil
}
