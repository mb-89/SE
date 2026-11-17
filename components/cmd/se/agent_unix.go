//go:build !windows

package main

import (
	"fmt"
	"io"
	"os"
	"syscall"

	"golang.org/x/sys/unix"
)

// start replaces se by the host at path with args: the host's exit code is
// se's. It answers only where it cannot.
func start(path string, args []string, stderr io.Writer) int {
	err := syscall.Exec(path, append([]string{path}, args...), os.Environ())
	fmt.Fprintf(stderr, "se agent: cannot start %s: %v\n", path, err)
	return 1
}

// terminal reports whether f is a terminal, as its termios call says: a
// character device such as /dev/null is none.
func terminal(f *os.File) bool {
	_, err := unix.IoctlGetTermios(int(f.Fd()), ioctlReadTermios)
	return err == nil
}
