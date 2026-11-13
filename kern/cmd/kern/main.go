// Command kern is the bare core: the index, its bus and its host, with no
// component of an application compiled in. Its commands are the package cli's.
package main

import (
	"os"

	"github.com/mb-89/kern/cli"
)

func main() { os.Exit(cli.Run("kern", os.Args[1:], os.Stdout, os.Stderr)) }
