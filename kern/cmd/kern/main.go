// Command kern is the bare core: the index, its bus and its host, with no
// component of an application compiled in. It carries kern's own shared
// components, which run only where a checkout's wiring.toml places an
// instance. Its commands are the package cli's.
package main

import (
	"os"

	"github.com/mb-89/kern/cli"
	// kern's shared components, one blank import each.
	_ "github.com/mb-89/kern/components/github"
)

func main() { os.Exit(cli.Run("kern", os.Args[1:], os.Stdout, os.Stderr)) }
